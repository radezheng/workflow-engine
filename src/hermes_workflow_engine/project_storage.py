from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .config import HWEConfig, load_config
from .storage import now_iso


class ProjectStorageError(ValueError):
    """Raised when a project storage operation is invalid."""


@dataclass(frozen=True)
class ProjectPaths:
    project_root: Path
    engine_dir: Path
    db_path: Path


def paths_for_project(project_root: Path) -> ProjectPaths:
    root = project_root.expanduser().resolve()
    engine_dir = root / ".engine"
    return ProjectPaths(project_root=root, engine_dir=engine_dir, db_path=engine_dir / "engine.db")


def resolve_project_root(name_or_path: str, config: HWEConfig | None = None) -> Path:
    path = Path(name_or_path).expanduser()
    if path.is_absolute() or len(path.parts) > 1:
        return path.resolve()
    config = load_config() if config is None else config
    if config.default_workspace_root is None:
        raise ProjectStorageError("Project name requires HWE config `default_workspace_root`; pass an absolute path or run `hwe config init`.")
    return (config.default_workspace_root / path).resolve()


def _schema_sql() -> str:
    schema_path = Path(__file__).resolve().parents[2] / "schema" / "engine_schema.sql"
    if not schema_path.exists():
        raise ProjectStorageError(f"Project schema file not found: {schema_path}")
    return schema_path.read_text(encoding="utf-8")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


class ProjectStorage:
    def __init__(self, project_root: Path):
        self.paths = paths_for_project(project_root)
        self.project_root = self.paths.project_root
        self.engine_dir = self.paths.engine_dir
        self.db_path = self.paths.db_path
        self.engine_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(_schema_sql())

    def upsert_project(self, name: str, *, project_id: str | None = None, repo_path: Path | None = None) -> dict[str, Any]:
        self.initialize()
        timestamp = now_iso()
        project_id = project_id or name
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO projects(id, name, root_path, repo_path, status, created_at, updated_at)
                VALUES(?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    root_path=excluded.root_path,
                    repo_path=excluded.repo_path,
                    updated_at=excluded.updated_at
                """,
                (project_id, name, str(self.project_root), str(repo_path.resolve()) if repo_path else str(self.project_root), timestamp, timestamp),
            )
        self.event(project_id, None, None, None, "project_upserted", {"name": name, "root_path": str(self.project_root)})
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise ProjectStorageError(f"Unknown project: {project_id}")
        return dict(row)

    def list_projects(self) -> list[dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM projects ORDER BY updated_at DESC, name").fetchall()
        return [dict(row) for row in rows]

    def create_workitem(
        self,
        project_id: str,
        title: str,
        *,
        workitem_type: str = "feature",
        requirements: str = "",
        constraints: str = "",
        acceptance: list[str] | None = None,
        priority: int = 100,
        risk_level: str = "medium",
    ) -> dict[str, Any]:
        self.get_project(project_id)
        timestamp = now_iso()
        workitem_id = _id("wi")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO workitems(id, project_id, title, type, status, priority, risk_level, requirements_md, constraints_md, created_at, updated_at)
                VALUES(?, ?, ?, ?, 'ready', ?, ?, ?, ?, ?, ?)
                """,
                (workitem_id, project_id, title, workitem_type, priority, risk_level, requirements, constraints, timestamp, timestamp),
            )
            for ordinal, statement in enumerate(acceptance or [], start=1):
                connection.execute(
                    """
                    INSERT INTO acceptance_criteria(id, workitem_id, ordinal, statement, created_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (_id("ac"), workitem_id, ordinal, statement, timestamp, timestamp),
                )
        self.event(project_id, workitem_id, None, None, "workitem_created", {"title": title})
        return self.get_workitem(workitem_id)

    def get_workitem(self, workitem_id: str) -> dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM workitems WHERE id=?", (workitem_id,)).fetchone()
        if row is None:
            raise ProjectStorageError(f"Unknown workitem: {workitem_id}")
        return dict(row)

    def list_workitems(self, project_id: str) -> list[dict[str, Any]]:
        self.get_project(project_id)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM workitems WHERE project_id=? ORDER BY priority, created_at",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_role_prompt_template(
        self,
        project_id: str,
        role: str,
        name: str,
        body: str,
        *,
        version: str = "0.1.0",
        description: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        self.get_project(project_id)
        timestamp = now_iso()
        template_id = _id("prompt")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO role_prompt_templates(id, project_id, role, name, version, description, body_md, tags_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (template_id, project_id, role, name, version, description, body, _json(tags or []), timestamp, timestamp),
            )
        self.event(project_id, None, None, None, "role_prompt_template_created", {"role": role, "name": name, "version": version})
        return self.get_role_prompt_template(template_id)

    def get_role_prompt_template(self, template_id: str) -> dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM role_prompt_templates WHERE id=?", (template_id,)).fetchone()
        if row is None:
            raise ProjectStorageError(f"Unknown role prompt template: {template_id}")
        template = dict(row)
        template["tags"] = json.loads(template.pop("tags_json"))
        return template

    def list_role_prompt_templates(self, project_id: str, *, role: str | None = None) -> list[dict[str, Any]]:
        self.get_project(project_id)
        query = "SELECT * FROM role_prompt_templates WHERE project_id=?"
        params: list[Any] = [project_id]
        if role:
            query += " AND role=?"
            params.append(role)
        query += " ORDER BY role, name, version"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        templates = []
        for row in rows:
            template = dict(row)
            template["tags"] = json.loads(template.pop("tags_json"))
            templates.append(template)
        return templates

    def create_workflow(self, project_id: str, workitem_id: str, *, planner_profile: str | None = None) -> dict[str, Any]:
        workitem = self.get_workitem(workitem_id)
        if workitem["project_id"] != project_id:
            raise ProjectStorageError("Workitem does not belong to project.")
        timestamp = now_iso()
        workflow_id = _id("wf")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO project_workflows(id, project_id, workitem_id, status, planner_profile, created_at, updated_at)
                VALUES(?, ?, ?, 'planning', ?, ?, ?)
                """,
                (workflow_id, project_id, workitem_id, planner_profile, timestamp, timestamp),
            )
            connection.execute(
                "UPDATE workitems SET current_workflow_id=?, status='planning', updated_at=? WHERE id=?",
                (workflow_id, timestamp, workitem_id),
            )
        self.event(project_id, workitem_id, workflow_id, None, "workflow_created", {"planner_profile": planner_profile})
        return self.get_workflow(workflow_id)

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM project_workflows WHERE id=?", (workflow_id,)).fetchone()
        if row is None:
            raise ProjectStorageError(f"Unknown workflow: {workflow_id}")
        return dict(row)

    def create_task(
        self,
        workflow_id: str,
        title: str,
        *,
        kind: str,
        profile: str | None = None,
        depends_on: list[str] | None = None,
        outputs: list[str] | None = None,
        gates: list[str] | None = None,
        skills: list[str] | None = None,
        prompt_template_id: str | None = None,
        prompt_text: str | None = None,
        priority: int = 100,
        risk_level: str = "medium",
        created_by: str | None = None,
        created_reason: str | None = None,
    ) -> dict[str, Any]:
        workflow = self.get_workflow(workflow_id)
        timestamp = now_iso()
        task_id = _id("task")
        dependencies = depends_on or []
        status = "pending" if dependencies else "ready"
        with self.connect() as connection:
            if prompt_template_id:
                template_row = connection.execute(
                    "SELECT 1 FROM role_prompt_templates WHERE id=? AND project_id=?",
                    (prompt_template_id, workflow["project_id"]),
                ).fetchone()
                if template_row is None:
                    raise ProjectStorageError(f"Unknown prompt template for project {workflow['project_id']}: {prompt_template_id}")
            for dependency in dependencies:
                if connection.execute("SELECT 1 FROM tasks WHERE id=? AND workflow_id=?", (dependency, workflow_id)).fetchone() is None:
                    raise ProjectStorageError(f"Unknown dependency for workflow {workflow_id}: {dependency}")
            connection.execute(
                """
                INSERT INTO tasks(id, workflow_id, workitem_id, title, kind, profile, status, priority, risk_level, prompt_template_id, prompt_text, skills_json, outputs_json, gates_json, created_by, created_reason, created_at, updated_at, ready_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    workflow_id,
                    workflow["workitem_id"],
                    title,
                    kind,
                    profile,
                    status,
                    priority,
                    risk_level,
                    prompt_template_id,
                    prompt_text,
                    _json(skills or []),
                    _json(outputs or []),
                    _json(gates or []),
                    created_by,
                    created_reason,
                    timestamp,
                    timestamp,
                    timestamp if status == "ready" else None,
                ),
            )
            for dependency in dependencies:
                connection.execute(
                    "INSERT INTO task_dependencies(task_id, depends_on_task_id, created_at) VALUES(?, ?, ?)",
                    (task_id, dependency, timestamp),
                )
        self.event(workflow["project_id"], workflow["workitem_id"], workflow_id, task_id, "task_created", {"status": status, "title": title})
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT tasks.*, project_workflows.project_id
                FROM tasks
                JOIN project_workflows ON project_workflows.id = tasks.workflow_id
                WHERE tasks.id=?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            raise ProjectStorageError(f"Unknown task: {task_id}")
        return self._decode_task(dict(row))

    def list_tasks(self, workflow_id: str) -> list[dict[str, Any]]:
        self.mark_ready_tasks(workflow_id)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE workflow_id=? ORDER BY priority, created_at",
                (workflow_id,),
            ).fetchall()
        return [self._decode_task(dict(row)) for row in rows]

    def mark_ready_tasks(self, workflow_id: str) -> int:
        timestamp = now_iso()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT task.id
                FROM tasks task
                WHERE task.workflow_id=? AND task.status='pending'
                  AND NOT EXISTS (
                    SELECT 1
                    FROM task_dependencies dependency
                    JOIN tasks upstream ON upstream.id = dependency.depends_on_task_id
                    WHERE dependency.task_id = task.id AND upstream.status != 'succeeded'
                  )
                """,
                (workflow_id,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE tasks SET status='ready', ready_at=?, updated_at=? WHERE id=?",
                    (timestamp, timestamp, row["id"]),
                )
        for row in rows:
            task = self.get_task(row["id"])
            self.event(task["project_id"], task["workitem_id"], workflow_id, task["id"], "task_ready", {})
        return len(rows)

    def claim_next_task(self, workflow_id: str, *, worker_id: str, profile: str | None = None, lease_seconds: int = 900) -> dict[str, Any] | None:
        self.mark_ready_tasks(workflow_id)
        timestamp = now_iso()
        expires_at = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
        claim_id = _id("claim")
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM tasks
                WHERE workflow_id=? AND status='ready' AND (? IS NULL OR profile=? OR profile IS NULL)
                ORDER BY priority, created_at
                LIMIT 1
                """,
                (workflow_id, profile, profile),
            ).fetchone()
            if row is None:
                return None
            task = dict(row)
            connection.execute(
                """
                INSERT INTO worker_claims(id, task_id, worker_id, profile, status, claimed_at, expires_at)
                VALUES(?, ?, ?, ?, 'claimed', ?, ?)
                """,
                (claim_id, task["id"], worker_id, profile, timestamp, expires_at),
            )
            connection.execute(
                "UPDATE tasks SET status='claimed', attempt=attempt+1, updated_at=? WHERE id=?",
                (timestamp, task["id"]),
            )
        claimed = self.get_task(task["id"])
        claimed["claim_id"] = claim_id
        self.event(claimed["project_id"], claimed["workitem_id"], workflow_id, claimed["id"], "task_claimed", {"worker_id": worker_id, "claim_id": claim_id})
        return claimed

    def complete_task(self, task_id: str, *, status: str = "succeeded", result: dict[str, Any] | None = None) -> dict[str, Any]:
        if status not in {"succeeded", "failed", "cancelled", "waiting_for_info", "waiting_for_approval"}:
            raise ProjectStorageError(f"Unsupported completion status: {status}")
        task = self.get_task(task_id)
        timestamp = now_iso()
        with self.connect() as connection:
            connection.execute(
                "UPDATE tasks SET status=?, completed_at=?, updated_at=? WHERE id=?",
                (status, timestamp if status in {"succeeded", "failed", "cancelled"} else None, timestamp, task_id),
            )
            connection.execute(
                "UPDATE worker_claims SET status='released', released_at=?, release_reason=? WHERE task_id=? AND status='claimed'",
                (timestamp, status, task_id),
            )
        self.event(task["project_id"], task["workitem_id"], task["workflow_id"], task_id, "task_completed", {"status": status, "result": result or {}})
        self.mark_ready_tasks(task["workflow_id"])
        return self.get_task(task_id)

    def list_events(self, project_id: str | None = None, *, limit: int = 50) -> list[dict[str, Any]]:
        self.initialize()
        query = "SELECT * FROM project_events"
        params: tuple[Any, ...] = ()
        if project_id:
            query += " WHERE project_id=?"
            params = (project_id,)
        query += " ORDER BY id DESC LIMIT ?"
        with self.connect() as connection:
            rows = connection.execute(query, (*params, limit)).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["payload"] = json.loads(event.pop("payload_json"))
            events.append(event)
        return list(reversed(events))

    def event(
        self,
        project_id: str | None,
        workitem_id: str | None,
        workflow_id: str | None,
        task_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO project_events(project_id, workitem_id, workflow_id, task_id, type, payload_json, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, workitem_id, workflow_id, task_id, event_type, _json(payload), now_iso()),
            )

    def _decode_task(self, task: dict[str, Any]) -> dict[str, Any]:
        for key in ["context_contract_json", "skills_json", "outputs_json", "gates_json", "allowed_paths_json"]:
            output_key = key.removesuffix("_json")
            task[output_key] = json.loads(task.pop(key))
        return task