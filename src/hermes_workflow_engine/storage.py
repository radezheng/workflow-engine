from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .spec import WorkflowSpec


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Storage:
    def __init__(self, engine_dir: Path):
        self.engine_dir = engine_dir
        self.db_path = engine_dir / "engine.db"
        self.engine_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflows(
                    id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS steps(
                    id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    profile TEXT,
                    state TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    spec_json TEXT NOT NULL,
                    PRIMARY KEY(id, workflow_id)
                );
                CREATE TABLE IF NOT EXISTS edges(
                    workflow_id TEXT NOT NULL,
                    from_step TEXT NOT NULL,
                    to_step TEXT NOT NULL,
                    edge_policy TEXT NOT NULL,
                    PRIMARY KEY(workflow_id, from_step, to_step)
                );
                CREATE TABLE IF NOT EXISTS runs(
                    id TEXT PRIMARY KEY,
                    step_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    exit_code INTEGER
                );
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id TEXT NOT NULL,
                    step_id TEXT,
                    run_id TEXT,
                    type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS context_bundles(
                    id TEXT PRIMARY KEY,
                    step_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    step_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    sha256 TEXT,
                    diff_path TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gate_results(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    step_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    gate TEXT NOT NULL,
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    findings_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    step_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    approver TEXT NOT NULL,
                    status TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def upsert_workflow(self, spec: WorkflowSpec) -> None:
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO workflows(id, version, workspace, status, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    version=excluded.version,
                    workspace=excluded.workspace,
                    updated_at=excluded.updated_at
                """,
                (spec.id, spec.version, str(spec.workspace), "loaded", timestamp, timestamp),
            )
            current_step_ids = [step.id for step in spec.steps]
            placeholders = ",".join("?" for _ in current_step_ids)
            connection.execute(
                f"DELETE FROM steps WHERE workflow_id=? AND id NOT IN ({placeholders})",
                (spec.id, *current_step_ids),
            )
            connection.execute(
                f"DELETE FROM edges WHERE workflow_id=? AND (from_step NOT IN ({placeholders}) OR to_step NOT IN ({placeholders}))",
                (spec.id, *current_step_ids, *current_step_ids),
            )
            for step in spec.steps:
                existing = connection.execute(
                    "SELECT state, attempt FROM steps WHERE workflow_id=? AND id=?",
                    (spec.id, step.id),
                ).fetchone()
                state = existing["state"] if existing else "pending"
                attempt = int(existing["attempt"]) if existing else 0
                connection.execute(
                    """
                    INSERT INTO steps(id, workflow_id, title, kind, profile, state, attempt, spec_json)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id, workflow_id) DO UPDATE SET
                        title=excluded.title,
                        kind=excluded.kind,
                        profile=excluded.profile,
                        spec_json=excluded.spec_json
                    """,
                    (step.id, spec.id, step.title, step.kind, step.profile, state, attempt, json.dumps(step.raw, sort_keys=True)),
                )
                for need in step.needs:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO edges(workflow_id, from_step, to_step, edge_policy)
                        VALUES(?, ?, ?, ?)
                        """,
                        (spec.id, need, step.id, "completed_or_approved"),
                    )
        self.event(spec.id, None, None, "workflow_loaded", {"steps": len(spec.steps)})

    def step_state(self, workflow_id: str, step_id: str) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT state FROM steps WHERE workflow_id=? AND id=?",
                (workflow_id, step_id),
            ).fetchone()
        return str(row["state"]) if row else "pending"

    def step_attempt(self, workflow_id: str, step_id: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT attempt FROM steps WHERE workflow_id=? AND id=?",
                (workflow_id, step_id),
            ).fetchone()
        return int(row["attempt"]) if row else 0

    def set_step_state(self, workflow_id: str, step_id: str, state: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE steps SET state=? WHERE workflow_id=? AND id=?",
                (state, workflow_id, step_id),
            )
        self.event(workflow_id, step_id, None, "step_state_changed", {"state": state})

    def bump_attempt(self, workflow_id: str, step_id: str) -> int:
        with self.connect() as connection:
            connection.execute(
                "UPDATE steps SET attempt=attempt+1 WHERE workflow_id=? AND id=?",
                (workflow_id, step_id),
            )
            row = connection.execute(
                "SELECT attempt FROM steps WHERE workflow_id=? AND id=?",
                (workflow_id, step_id),
            ).fetchone()
        return int(row["attempt"])

    def create_run(self, workflow_id: str, step_id: str, attempt: int) -> str:
        run_id = f"run_{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}_{step_id}"
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO runs(id, step_id, workflow_id, attempt, status, started_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (run_id, step_id, workflow_id, attempt, "started", now_iso()),
            )
        self.event(workflow_id, step_id, run_id, "run_started", {"attempt": attempt})
        return run_id

    def finish_run(self, workflow_id: str, step_id: str, run_id: str, status: str, exit_code: int | None) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE runs SET status=?, ended_at=?, exit_code=? WHERE id=?",
                (status, now_iso(), exit_code, run_id),
            )
        self.event(workflow_id, step_id, run_id, "run_finished", {"status": status, "exit_code": exit_code})

    def record_context_bundle(
        self,
        workflow_id: str,
        step_id: str,
        run_id: str,
        bundle_id: str,
        path: Path,
        manifest: dict[str, Any],
        sha256: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO context_bundles(id, step_id, workflow_id, run_id, path, manifest_json, sha256, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (bundle_id, step_id, workflow_id, run_id, str(path), json.dumps(manifest, sort_keys=True), sha256, now_iso()),
            )
        self.event(workflow_id, step_id, run_id, "context_compiled", {"bundle_id": bundle_id, "sha256": sha256})

    def record_gate_result(self, workflow_id: str, step_id: str, run_id: str, result: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO gate_results(step_id, workflow_id, run_id, gate, status, severity, findings_json, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step_id,
                    workflow_id,
                    run_id,
                    result["gate"],
                    result["status"],
                    result["severity"],
                    json.dumps(result.get("findings", []), sort_keys=True),
                    now_iso(),
                ),
            )
        self.event(workflow_id, step_id, run_id, "gate_result", result)

    def record_artifact(
        self,
        workflow_id: str,
        step_id: str,
        run_id: str,
        path: str,
        kind: str,
        sha256: str | None,
        diff_path: str | None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO artifacts(step_id, workflow_id, run_id, path, kind, sha256, diff_path, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (step_id, workflow_id, run_id, path, kind, sha256, diff_path, now_iso()),
            )

    def event(
        self,
        workflow_id: str,
        step_id: str | None,
        run_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO events(workflow_id, step_id, run_id, type, payload_json, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (workflow_id, step_id, run_id, event_type, json.dumps(payload, sort_keys=True), now_iso()),
            )

    def list_steps(self, workflow_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, title, kind, profile, state, attempt FROM steps WHERE workflow_id=? ORDER BY rowid",
                (workflow_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, workflow_id: str, limit: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, step_id, run_id, type, payload_json, created_at
                FROM events
                WHERE workflow_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (workflow_id, limit),
            ).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["payload"] = json.loads(event.pop("payload_json"))
            events.append(event)
        return list(reversed(events))

    def reset_workflow(self, workflow_id: str) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE steps SET state='pending', attempt=0 WHERE workflow_id=?", (workflow_id,))
            connection.execute("UPDATE workflows SET status='loaded', updated_at=? WHERE id=?", (now_iso(), workflow_id))
        self.event(workflow_id, None, None, "workflow_reset", {})