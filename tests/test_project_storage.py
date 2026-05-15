from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from hermes_workflow_engine.cli import main
from hermes_workflow_engine.config import HWEConfig
from hermes_workflow_engine.project_runtime import ProjectRuntime
from hermes_workflow_engine.project_storage import ProjectStorage, ProjectStorageError


@pytest.fixture(autouse=True)
def isolate_local_hwe_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HWE_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)


def test_project_workitem_workflow_task_lifecycle(tmp_path: Path) -> None:
    project_root = tmp_path / "alpha"
    storage = ProjectStorage(project_root)

    project = storage.upsert_project("alpha")
    workitem = storage.create_workitem(
        project["id"],
        "Add notes",
        requirements="Support Markdown notes.",
        acceptance=["Create notes", "Preview Markdown"],
    )
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    first_task = storage.create_task(
        workflow["id"],
        "Design notes",
        kind="design",
        profile="reviewer",
        skills=["hermes-project-workflow"],
        prompt_template_ref="reviewer/implementation-review",
    )
    second_task = storage.create_task(
        workflow["id"],
        "Implement notes",
        kind="code",
        profile="coder",
        depends_on=[first_task["id"]],
        outputs=["backend/notes.py"],
        gates=["python_syntax_ok"],
    )

    assert first_task["status"] == "ready"
    assert first_task["skills"] == ["hermes-project-workflow"]
    assert first_task["prompt_template_ref"] == "reviewer/implementation-review"
    assert second_task["status"] == "pending"
    assert storage.list_workitems(project["id"])[0]["status"] == "in_progress"

    running = storage.claim_next_task(workflow["id"], worker_id="worker-1", profile="reviewer")
    assert running is not None
    assert running["id"] == first_task["id"]
    assert running["status"] == "running"
    assert running["attempt"] == 1
    assert running["claim_id"].startswith("claim_")
    assert storage.list_workitems(project["id"])[0]["status"] == "in_progress"

    completed = storage.complete_task(first_task["id"])
    assert completed["status"] == "succeeded"

    tasks = {task["id"]: task for task in storage.list_tasks(workflow["id"])}
    assert tasks[first_task["id"]]["status"] == "succeeded"
    assert tasks[second_task["id"]]["status"] == "ready"
    assert tasks[second_task["id"]]["outputs"] == ["backend/notes.py"]
    assert tasks[second_task["id"]]["gates"] == ["python_syntax_ok"]
    assert storage.list_workitems(project["id"])[0]["status"] == "in_progress"

    storage.complete_task(second_task["id"])
    assert storage.list_workitems(project["id"])[0]["status"] == "succeeded"

    events = storage.list_events(project["id"])
    event_types = [event["type"] for event in events]
    assert "project_upserted" in event_types
    assert "task_ready" in event_types
    assert "task_running" in event_types
    assert "task_completed" in event_types
    assert (project_root / ".engine" / "engine.db").exists()


def test_list_workitems_orders_newest_first(tmp_path: Path) -> None:
    project_root = tmp_path / "ordered-workitems"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("ordered-workitems")
    older = storage.create_workitem(project["id"], "Older workitem")
    newer = storage.create_workitem(project["id"], "Newer workitem")
    with storage.connect() as connection:
        connection.execute("UPDATE workitems SET created_at=? WHERE id=?", ("2026-01-01T00:00:00+00:00", older["id"]))
        connection.execute("UPDATE workitems SET created_at=? WHERE id=?", ("2026-01-02T00:00:00+00:00", newer["id"]))

    items = storage.list_workitems(project["id"])

    assert [item["id"] for item in items] == [newer["id"], older["id"]]


def test_workitem_archive_restore_hides_and_preserves_synced_status(tmp_path: Path) -> None:
    project_root = tmp_path / "archive-workitem"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("archive-workitem")
    workitem = storage.create_workitem(project["id"], "Archived feature")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="designer")
    task = storage.create_task(workflow["id"], "Implement archived feature", kind="agent", profile="coder")
    storage.complete_task(task["id"])

    assert storage.list_workitems(project["id"])[0]["status"] == "succeeded"

    archived = storage.archive_workitem(workitem["id"])

    assert archived["status"] == "archived"
    assert storage.list_workitems(project["id"]) == []
    assert storage.list_workitems(project["id"], include_archived=True)[0]["status"] == "archived"

    restored = storage.restore_workitem(workitem["id"])

    assert restored["status"] == "succeeded"
    assert storage.list_workitems(project["id"])[0]["id"] == workitem["id"]
    event_types = [event["type"] for event in storage.list_events(project["id"])]
    assert "workitem_archived" in event_types
    assert "workitem_restored" in event_types


def test_project_init_cli_writes_project_database(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "cli-project"

    exit_code = main(["project", "init", str(project_root), "--id", "cli", "--name", "CLI Project"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "cli"
    assert payload["name"] == "CLI Project"
    assert payload["root_path"] == str(project_root.resolve())
    assert (project_root / ".engine" / "engine.db").exists()


def test_project_archive_and_restore_hides_from_default_list(tmp_path: Path) -> None:
    project_root = tmp_path / "archive-project"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("Archive Project", project_id="archive-project")

    archived = storage.archive_project(project["id"])

    assert archived["status"] == "archived"
    assert storage.list_projects() == []
    assert storage.list_projects(include_archived=True)[0]["id"] == project["id"]
    event_types = [event["type"] for event in storage.list_events(project["id"])]
    assert "project_archived" in event_types

    restored = storage.restore_project(project["id"])

    assert restored["status"] == "active"
    assert storage.list_projects()[0]["id"] == project["id"]
    event_types = [event["type"] for event in storage.list_events(project["id"])]
    assert "project_restored" in event_types


def test_project_archive_restore_cli(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "cli-archive-project"

    assert main(["project", "init", str(project_root), "--id", "cli-archive", "--name", "CLI Archive"]) == 0
    capsys.readouterr()
    assert main(["project", "archive", str(project_root), "--id", "cli-archive"]) == 0
    archived = json.loads(capsys.readouterr().out)

    assert archived["status"] == "archived"

    assert main(["project", "restore", str(project_root), "--id", "cli-archive"]) == 0
    restored = json.loads(capsys.readouterr().out)

    assert restored["status"] == "active"


def test_task_waiting_for_info_creates_human_action_and_answer_resumes(tmp_path: Path) -> None:
    project_root = tmp_path / "human-info"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("human-info")
    workitem = storage.create_workitem(project["id"], "Clarify notes storage")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    task = storage.create_task(workflow["id"], "Plan persistence", kind="design", profile="reviewer")

    assert storage.claim_next_task(workflow["id"], worker_id="worker-1", profile="reviewer") is not None
    waiting = storage.complete_task(
        task["id"],
        status="waiting_for_info",
        result={"reason": "Persistence target affects design."},
        human_action_title="Choose persistence target",
        human_action_body="Should notes use PostgreSQL or browser storage?",
        questions=[{"id": "q1", "question": "Where should notes be stored?"}],
        options=["PostgreSQL", "Local browser only"],
        requested_by="reviewer",
    )

    assert waiting["status"] == "waiting_for_info"
    action = waiting["human_action"]
    assert action["kind"] == "info_request"
    assert action["questions"] == [{"id": "q1", "question": "Where should notes be stored?"}]
    assert storage.list_human_actions(project["id"], status="pending") == [action]

    resolved = storage.resolve_human_action(action["id"], resolution="answered", response={"text": "PostgreSQL"}, resolved_by="human")

    assert resolved["status"] == "answered"
    assert resolved["response"] == {"text": "PostgreSQL"}
    assert storage.get_task(task["id"])["status"] == "ready"
    assert storage.claim_next_task(workflow["id"], worker_id="worker-2", profile="reviewer")["id"] == task["id"]


def test_human_action_approval_cli_resumes_task(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "approval-project"
    assert main(["project", "init", str(project_root), "--id", "approval-project"]) == 0
    capsys.readouterr()

    assert main(["workitem", "create", str(project_root), "Run migration", "--project-id", "approval-project"]) == 0
    workitem = json.loads(capsys.readouterr().out)
    assert main(["workflow", "create", str(project_root), workitem["id"], "--project-id", "approval-project"]) == 0
    workflow = json.loads(capsys.readouterr().out)
    assert main(["task", "create", str(project_root), workflow["id"], "Approve migration", "--kind", "approval", "--profile", "reviewer"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert main(["task", "claim", str(project_root), workflow["id"], "--worker-id", "worker-1", "--profile", "reviewer"]) == 0
    capsys.readouterr()

    assert main(
        [
            "task",
            "complete",
            str(project_root),
            task["id"],
            "--status",
            "waiting_for_approval",
            "--title",
            "Approve migration",
            "--body",
            "Run a project-local migration.",
            "--option",
            "approve",
            "--option",
            "reject",
            "--evidence",
            "backend/migration.sql",
            "--requested-by",
            "reviewer",
        ]
    ) == 0
    waiting = json.loads(capsys.readouterr().out)
    action_id = waiting["human_action"]["id"]
    assert waiting["status"] == "waiting_for_approval"

    assert main(["approve", str(project_root), action_id, "--project-id", "approval-project", "--text", "Approved for dev DB"]) == 0
    approved = json.loads(capsys.readouterr().out)
    assert approved["status"] == "approved"
    assert main(["task", "list", str(project_root), workflow["id"]]) == 0
    tasks = json.loads(capsys.readouterr().out)
    assert tasks[0]["status"] == "ready"


def test_human_action_create_cli(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "human-action-create"
    assert main(["project", "init", str(project_root), "--id", "human-action-create"]) == 0
    capsys.readouterr()

    assert main(["workitem", "create", str(project_root), "Clarify indicators", "--project-id", "human-action-create"]) == 0
    workitem = json.loads(capsys.readouterr().out)
    assert main(["workflow", "create", str(project_root), workitem["id"], "--project-id", "human-action-create"]) == 0
    workflow = json.loads(capsys.readouterr().out)

    assert main(
        [
            "human-action",
            "create",
            str(project_root),
            "Confirm credit-cycle indicators",
            "--project-id",
            "human-action-create",
            "--workitem-id",
            workitem["id"],
            "--workflow-id",
            workflow["id"],
            "--body",
            "Confirm the indicator set before source research.",
            "--question",
            "Which credit-cycle indicators should be in scope?",
            "--option",
            "Credit/GDP, policy rates, private-sector debt",
            "--requested-by",
            "designer",
        ]
    ) == 0
    action = json.loads(capsys.readouterr().out)
    assert action["kind"] == "info_request"
    assert action["status"] == "pending"
    assert action["questions"] == [{"id": "q1", "question": "Which credit-cycle indicators should be in scope?"}]
    assert action["options"] == ["Credit/GDP, policy rates, private-sector debt"]

    assert main(["human-action", "list", str(project_root), "--project-id", "human-action-create", "--status", "pending"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == action["id"]


def test_task_create_rejects_fake_human_action_kind(tmp_path: Path) -> None:
    project_root = tmp_path / "reject-fake-human-task"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("reject-fake-human-task")
    workitem = storage.create_workitem(project["id"], "Clarify scope")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="designer")

    with pytest.raises(ProjectStorageError, match="Human input must be represented"):
        storage.create_task(workflow["id"], "Fake human action", kind="human-action", profile="default")


def test_standalone_pending_human_action_blocks_workitem_success(tmp_path: Path) -> None:
    project_root = tmp_path / "standalone-human-action"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("standalone-human-action")
    workitem = storage.create_workitem(project["id"], "Clarify indicators")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="designer")
    task = storage.create_task(workflow["id"], "Plan research", kind="command", profile="command")
    storage.complete_task(task["id"], status="succeeded")

    assert storage.get_workitem(workitem["id"])["status"] == "succeeded"

    action = storage.create_human_action(
        project["id"],
        kind="info_request",
        title="Confirm indicators",
        body="Choose the core indicator set before continuing.",
        workitem_id=workitem["id"],
        workflow_id=workflow["id"],
        questions=[{"id": "q1", "question": "Which indicators are in scope?"}],
        options=["Credit/GDP and policy rates"],
        requested_by="reviewer",
    )

    assert storage.get_workitem(workitem["id"])["status"] == "waiting_for_human"

    storage.resolve_human_action(action["id"], resolution="answered", response={"text": "Credit/GDP and policy rates"}, resolved_by="human")

    assert storage.get_workitem(workitem["id"])["status"] == "succeeded"


def test_project_runtime_runs_command_task(tmp_path: Path) -> None:
    project_root = tmp_path / "runtime-project"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("runtime-project")
    workitem = storage.create_workitem(project["id"], "Create marker", requirements="Write a marker file.")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    task = storage.create_task(
        workflow["id"],
        "Write marker",
        kind="command",
        profile="command",
        prompt_text="python3 -c \"from pathlib import Path; import sys; Path('marker.txt').write_text('ok', encoding='utf-8'); print('console-out'); print('console-err', file=sys.stderr)\"",
        outputs=["marker.txt"],
    )

    summary = ProjectRuntime(storage).run_workitem(project["id"], workitem["id"])

    assert summary.tasks_started == 1
    assert summary.tasks_succeeded == 1
    assert summary.blocked == []
    assert (project_root / "marker.txt").read_text(encoding="utf-8") == "ok"
    assert storage.get_task(task["id"])["status"] == "succeeded"
    run = storage.list_task_runs(task_id=task["id"])[0]
    stdout_text = Path(run["stdout_path"]).read_text(encoding="utf-8")
    stderr_text = Path(run["stderr_path"]).read_text(encoding="utf-8")
    assert "kind: command" in stdout_text
    assert "$ python3 -c" in stdout_text
    assert "console-out" in stdout_text
    assert "# HWE exit_code: 0" in stdout_text
    assert "kind: command" in stderr_text
    assert "console-err" in stderr_text
    assert "# HWE exit_code: 0" in stderr_text
    event_types = [event["type"] for event in storage.list_events(project["id"])]
    assert "workitem_run_requested" in event_types
    assert "workitem_run_completed" in event_types


def test_project_runtime_runs_specific_ready_task(tmp_path: Path) -> None:
    project_root = tmp_path / "specific-task-runtime"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("specific-task-runtime")
    workitem = storage.create_workitem(project["id"], "Run selected task")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    first = storage.create_task(workflow["id"], "First ready", kind="command", profile="command", prompt_text="python3 -c \"from pathlib import Path; Path('first.txt').write_text('first', encoding='utf-8')\"", priority=10)
    second = storage.create_task(workflow["id"], "Second ready", kind="command", profile="command", prompt_text="python3 -c \"from pathlib import Path; Path('second.txt').write_text('second', encoding='utf-8')\"", priority=20)

    summary = ProjectRuntime(storage).run_one_task(project["id"], second["id"])

    assert summary.tasks_started == 1
    assert summary.tasks_succeeded == 1
    assert storage.get_task(first["id"])["status"] == "ready"
    assert storage.get_task(second["id"])["status"] == "succeeded"
    assert not (project_root / "first.txt").exists()
    assert (project_root / "second.txt").read_text(encoding="utf-8") == "second"
    event_types = [event["type"] for event in storage.list_events(project["id"])]
    assert "task_run_requested" in event_types
    assert "task_run_completed" in event_types


def test_project_runtime_records_no_ready_task_event(tmp_path: Path) -> None:
    project_root = tmp_path / "runtime-no-ready"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("runtime-no-ready")
    workitem = storage.create_workitem(project["id"], "No ready work")
    storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")

    summary = ProjectRuntime(storage).run_workitem(project["id"], workitem["id"])

    assert summary.tasks_started == 0
    events = storage.list_events(project["id"])
    no_ready = [event for event in events if event["type"] == "workitem_run_no_ready_task"][-1]
    assert no_ready["payload"]["tasks_started"] == 0


def test_project_runtime_runs_http_check_task(tmp_path: Path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                body = json.dumps({"status": "healthy", "database": "connected"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            _ = args
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        project_root = tmp_path / "http-check-project"
        storage = ProjectStorage(project_root)
        project = storage.upsert_project("http-check-project")
        workitem = storage.create_workitem(project["id"], "Smoke test API")
        workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
        task = storage.create_task(
            workflow["id"],
            "Check health endpoint",
            kind="http_check",
            profile="command",
            prompt_text=json.dumps(
                {
                    "requests": [
                        {
                            "url": f"http://127.0.0.1:{server.server_port}/health",
                            "expect_status": 200,
                            "expect_json": {"status": "healthy"},
                            "expect_contains": "connected",
                        }
                    ]
                }
            ),
        )

        summary = ProjectRuntime(storage).run_workitem(project["id"], workitem["id"])

        assert summary.tasks_started == 1
        assert summary.tasks_succeeded == 1
        assert summary.failed == []
        assert summary.blocked == []
        assert storage.get_task(task["id"])["status"] == "succeeded"
    finally:
        server.shutdown()


def test_project_runtime_http_check_failure_blocks_summary(tmp_path: Path) -> None:
    project_root = tmp_path / "http-check-failure"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("http-check-failure")
    workitem = storage.create_workitem(project["id"], "Smoke test API")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    task = storage.create_task(
        workflow["id"],
        "Check missing endpoint",
        kind="http_check",
        profile="command",
        prompt_text=json.dumps({"url": "http://127.0.0.1:1/missing", "retries": 1, "timeout_seconds": 0.1}),
    )

    summary = ProjectRuntime(storage).run_workitem(project["id"], workitem["id"])

    assert summary.tasks_failed == 1
    assert summary.failed == [task["id"]]
    assert summary.open == []


def test_task_release_cli_returns_running_task_to_ready(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "release-project"
    assert main(["project", "init", str(project_root), "--id", "release-project"]) == 0
    capsys.readouterr()
    assert main(["workitem", "create", str(project_root), "Release running task", "--project-id", "release-project"]) == 0
    workitem = json.loads(capsys.readouterr().out)
    assert main(["workflow", "create", str(project_root), workitem["id"], "--project-id", "release-project"]) == 0
    workflow = json.loads(capsys.readouterr().out)
    assert main(["task", "create", str(project_root), workflow["id"], "Run me", "--kind", "design", "--profile", "reviewer"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert main(["task", "claim", str(project_root), workflow["id"], "--worker-id", "worker-1", "--profile", "reviewer"]) == 0
    capsys.readouterr()

    assert main(["task", "release", str(project_root), task["id"], "--reason", "cancelled-run"]) == 0
    released = json.loads(capsys.readouterr().out)

    assert released["status"] == "ready"
    assert main(["task", "claim", str(project_root), workflow["id"], "--worker-id", "worker-2", "--profile", "reviewer"]) == 0
    rerun = json.loads(capsys.readouterr().out)
    assert rerun["id"] == task["id"]


def test_release_running_task_cancels_started_run(tmp_path: Path) -> None:
    project_root = tmp_path / "release-started-run"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("release-started-run")
    workitem = storage.create_workitem(project["id"], "Release abandoned run")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    task = storage.create_task(workflow["id"], "Run then abandon", kind="design", profile="reviewer")
    running = storage.claim_next_task(workflow["id"], worker_id="worker-1", profile="reviewer")
    run = storage.create_task_run(task["id"], claim_id=running["claim_id"], profile="reviewer")

    released = storage.release_task_claim(task["id"], reason="abandoned-run")

    assert released["status"] == "ready"
    cancelled_run = storage.get_task_run(run["id"])
    assert cancelled_run["status"] == "cancelled"
    assert cancelled_run["result"] == {"reason": "abandoned-run", "released": True}
    event = [event for event in storage.list_events(project["id"]) if event["type"] == "task_run_finished"][-1]
    assert event["run_id"] == run["id"]
    assert event["payload"]["status"] == "cancelled"


def test_task_reassign_cli_changes_ready_task_profile_after_release(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "reassign-project"
    assert main(["project", "init", str(project_root), "--id", "reassign-project"]) == 0
    capsys.readouterr()
    assert main(["workitem", "create", str(project_root), "Reassign task", "--project-id", "reassign-project"]) == 0
    workitem = json.loads(capsys.readouterr().out)
    assert main(["workflow", "create", str(project_root), workitem["id"], "--project-id", "reassign-project"]) == 0
    workflow = json.loads(capsys.readouterr().out)
    assert main(["task", "create", str(project_root), workflow["id"], "Research data", "--kind", "research", "--profile", "default"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert main(["task", "claim", str(project_root), workflow["id"], "--worker-id", "worker-1", "--profile", "default"]) == 0
    capsys.readouterr()
    assert main(["task", "release", str(project_root), task["id"], "--reason", "switch-profile"]) == 0
    capsys.readouterr()

    assert main(["task", "reassign", str(project_root), task["id"], "--profile", "designer", "--reason", "switch-profile"]) == 0
    reassigned = json.loads(capsys.readouterr().out)

    assert reassigned["status"] == "ready"
    assert reassigned["attempt"] == 1
    assert reassigned["profile"] == "designer"
    assert main(["task", "claim", str(project_root), workflow["id"], "--worker-id", "worker-2", "--profile", "default"]) == 1
    capsys.readouterr()
    assert main(["task", "claim", str(project_root), workflow["id"], "--worker-id", "worker-3", "--profile", "designer"]) == 0
    claimed = json.loads(capsys.readouterr().out)
    assert claimed["id"] == task["id"]


def test_task_retry_cli_returns_failed_task_to_ready(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "retry-project"
    assert main(["project", "init", str(project_root), "--id", "retry-project"]) == 0
    capsys.readouterr()
    assert main(["workitem", "create", str(project_root), "Retry failed", "--project-id", "retry-project"]) == 0
    workitem = json.loads(capsys.readouterr().out)
    assert main(["workflow", "create", str(project_root), workitem["id"], "--project-id", "retry-project"]) == 0
    workflow = json.loads(capsys.readouterr().out)
    assert main(["task", "create", str(project_root), workflow["id"], "Retry me", "--kind", "qa", "--profile", "reviewer"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert main(["task", "complete", str(project_root), task["id"], "--status", "failed"]) == 0
    failed = json.loads(capsys.readouterr().out)
    assert failed["status"] == "failed"

    assert main(["task", "retry", str(project_root), task["id"], "--reason", "transient-healthcheck"]) == 0
    retried = json.loads(capsys.readouterr().out)

    assert retried["status"] == "ready"
    assert main(["task", "claim", str(project_root), workflow["id"], "--worker-id", "worker-1", "--profile", "reviewer"]) == 0
    rerun = json.loads(capsys.readouterr().out)
    assert rerun["id"] == task["id"]


def test_superseded_task_is_terminal_and_unblocks_dependencies(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "superseded-project"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("superseded-project")
    workitem = storage.create_workitem(project["id"], "Replace duplicate task")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    first = storage.create_task(workflow["id"], "Old duplicate", kind="impl", profile="coder")
    second = storage.create_task(workflow["id"], "Continue after replacement", kind="command", profile="command", depends_on=[first["id"]], prompt_text="true")

    assert main(["task", "complete", str(project_root), first["id"], "--status", "superseded", "--result-json", '{"reason":"replacement task succeeded"}']) == 0
    capsys.readouterr()
    tasks = {task["id"]: task for task in storage.list_tasks(workflow["id"])}

    assert tasks[first["id"]]["status"] == "superseded"
    assert tasks[second["id"]]["status"] == "ready"

    summary = ProjectRuntime(storage).run_workitem(project["id"], workitem["id"])

    assert summary.tasks_succeeded == 1
    assert summary.failed == []
    assert summary.open == []
    assert summary.blocked == []


def test_run_workitem_cli_dry_run_agent_writes_prompt(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "agent-runtime"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("agent-runtime")
    workitem = storage.create_workitem(project["id"], "Design notes", requirements="Support Markdown notes.", constraints="Keep existing behavior.")
    template_path = project_root / ".engine" / "prompt-templates" / "reviewer" / "design-review.md"
    template_path.parent.mkdir(parents=True)
    template_path.write_text("Review design scope carefully.", encoding="utf-8")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    task = storage.create_task(
        workflow["id"],
        "Draft design",
        kind="design",
        profile="reviewer",
        prompt_template_ref="reviewer/design-review",
        prompt_text="Produce docs/design.md.",
        skills=["hermes-project-workflow"],
        outputs=["docs/design.md"],
    )

    assert main(["run-workitem", str(project_root), workitem["id"], "--project-id", project["id"], "--dry-run"]) == 0
    summary = json.loads(capsys.readouterr().out)

    assert summary["tasks_started"] == 1
    assert summary["tasks_succeeded"] == 1
    assert storage.get_task(task["id"])["status"] == "succeeded"
    run_started = [event for event in storage.list_events(project["id"]) if event["type"] == "task_run_started"][-1]
    assert run_started["run_id"] == run_started["payload"]["run_id"]
    run = storage.get_task_run(run_started["payload"]["run_id"])
    assert Path(run["stdout_path"]).exists()
    assert Path(run["stderr_path"]).exists()
    assert Path(run["prompt_path"]).exists()
    prompt = project_root / ".engine" / "runs" / run_started["payload"]["run_id"] / "prompt.md"
    prompt_text = prompt.read_text(encoding="utf-8")
    assert "Review design scope carefully." in prompt_text
    assert "# HWE 项目任务" in prompt_text
    assert "项目根目录：" in prompt_text
    assert "## 需求" in prompt_text
    assert "## 约束" in prompt_text
    assert "## 声明的技能" in prompt_text
    assert "## HWE 控制面" in prompt_text
    assert "HWE CLI" in prompt_text
    assert "不要使用未配置的 researcher/architect/developer/analyst" in prompt_text
    assert "如果缺少必要信息" in prompt_text
    assert "# HWE Project Task" not in prompt_text
    assert "## Requirements" not in prompt_text
    assert "## Declared Skills" not in prompt_text
    assert "Support Markdown notes." in prompt_text
    assert "hermes-project-workflow" in prompt_text


def test_project_runtime_runs_profile_switch_before_agent(tmp_path: Path) -> None:
    project_root = tmp_path / "switch-runtime"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("switch-runtime")
    workitem = storage.create_workitem(project["id"], "Switch before coding")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    task = storage.create_task(
        workflow["id"],
        "Use coder",
        kind="design",
        profile="coder",
        prompt_text="Do the work.",
    )
    fake_hermes = tmp_path / "fake_hermes.py"
    fake_hermes.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path('hermes_invoked.txt').write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n",
        encoding="utf-8",
    )
    switch_marker = project_root / "switch_marker.txt"
    config = HWEConfig(
        profiles={
            "coder": {
                "switch_command": f"python3 -c \"from pathlib import Path; Path('{switch_marker}').write_text('switched', encoding='utf-8')\"",
                "hermes_command": f"python3 {fake_hermes}",
            }
        }
    )

    summary = ProjectRuntime(storage, config=config).run_workitem(project["id"], workitem["id"])

    assert summary.tasks_started == 1
    assert summary.tasks_succeeded == 1
    assert storage.get_task(task["id"])["status"] == "succeeded"
    assert switch_marker.read_text(encoding="utf-8") == "switched"
    assert (project_root / "hermes_invoked.txt").read_text(encoding="utf-8").startswith("chat -p coder -Q --source workflow-engine")
    run = storage.list_task_runs(task_id=task["id"])[0]
    stdout_text = Path(run["stdout_path"]).read_text(encoding="utf-8")
    stderr_text = Path(run["stderr_path"]).read_text(encoding="utf-8")
    assert "kind: agent" in stdout_text
    assert "profile: coder" in stdout_text
    assert "chat -p coder -Q --source workflow-engine" in stdout_text
    assert "prompt.md" in stdout_text
    assert "Do the work." not in stdout_text
    assert "kind: agent" in stderr_text
    assert "# HWE exit_code: 0" in stderr_text


def test_project_runtime_tolerates_profile_switch_failure_by_default(tmp_path: Path) -> None:
    project_root = tmp_path / "switch-failure-runtime"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("switch-failure-runtime")
    workitem = storage.create_workitem(project["id"], "Switch failure should not block")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    task = storage.create_task(
        workflow["id"],
        "Use coder",
        kind="design",
        profile="coder",
        prompt_text="Do the work.",
    )
    fake_hermes = tmp_path / "fake_hermes.py"
    fake_hermes.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path('hermes_invoked.txt').write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n",
        encoding="utf-8",
    )
    config = HWEConfig(
        profiles={
            "coder": {
                "switch_command": "python3 -c \"import sys; sys.stderr.write('missing model\\n'); sys.exit(7)\"",
                "hermes_command": f"python3 {fake_hermes}",
            }
        }
    )

    summary = ProjectRuntime(storage, config=config).run_workitem(project["id"], workitem["id"])

    assert summary.tasks_started == 1
    assert summary.tasks_succeeded == 1
    assert storage.get_task(task["id"])["status"] == "succeeded"
    run = storage.list_task_runs(task_id=task["id"])[0]
    assert "WARNING: Model switch command failed with exit code 7" in Path(run["stderr_path"]).read_text(encoding="utf-8")
    assert (project_root / "hermes_invoked.txt").exists()


def test_project_runtime_interrupt_marks_run_and_task_cancelled(tmp_path: Path) -> None:
    project_root = tmp_path / "interrupt-runtime"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("interrupt-runtime")
    workitem = storage.create_workitem(project["id"], "Interrupt cleanly")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    task = storage.create_task(workflow["id"], "Interrupted agent", kind="agent", profile="coder", prompt_text="Do the work.")
    running = storage.claim_next_task(workflow["id"], worker_id="worker-1", profile="coder")
    class InterruptingRuntime(ProjectRuntime):
        def _run_agent_task(self, *args, **kwargs):
            _ = args, kwargs
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        InterruptingRuntime(storage, config=HWEConfig(profiles={"coder": {}})).run_task(running)

    cancelled_task = storage.get_task(task["id"])
    run = storage.list_task_runs(task_id=task["id"])[0]

    assert cancelled_task["status"] == "cancelled"
    assert run["status"] == "cancelled"
    assert run["result"]["error"] == "runtime_interrupted"
    assert "HWE task runtime interrupted" in Path(run["stderr_path"]).read_text(encoding="utf-8")


def test_project_runtime_runs_switch_commands_independently(tmp_path: Path) -> None:
    project_root = tmp_path / "switch-commands-runtime"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("switch-commands-runtime")
    workitem = storage.create_workitem(project["id"], "Switch commands should continue")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    task = storage.create_task(
        workflow["id"],
        "Use coder",
        kind="design",
        profile="coder",
        prompt_text="Do the work.",
    )
    fake_hermes = tmp_path / "fake_hermes.py"
    fake_hermes.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path('hermes_invoked.txt').write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n",
        encoding="utf-8",
    )
    switch_marker = project_root / "switch_marker.txt"
    config = HWEConfig(
        profiles={
            "coder": {
                "switch_commands": [
                    "python3 -c \"import sys; sys.stderr.write('not loaded\\n'); sys.exit(7)\"",
                    {
                        "command": f"python3 -c \"from pathlib import Path; Path('{switch_marker}').write_text('loaded', encoding='utf-8')\""
                    },
                ],
                "hermes_command": f"python3 {fake_hermes}",
            }
        }
    )

    summary = ProjectRuntime(storage, config=config).run_workitem(project["id"], workitem["id"])

    assert summary.tasks_started == 1
    assert summary.tasks_succeeded == 1
    assert storage.get_task(task["id"])["status"] == "succeeded"
    assert switch_marker.read_text(encoding="utf-8") == "loaded"
    run = storage.list_task_runs(task_id=task["id"])[0]
    stderr_text = Path(run["stderr_path"]).read_text(encoding="utf-8")
    assert "not loaded" in stderr_text
    assert "WARNING: Model switch command failed with exit code 7" in stderr_text
    assert (project_root / "hermes_invoked.txt").exists()


def test_project_runtime_retries_and_logs_healthcheck_failure(tmp_path: Path) -> None:
    project_root = tmp_path / "healthcheck-runtime"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("healthcheck-runtime")
    workitem = storage.create_workitem(project["id"], "Healthcheck should retry")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="designer")
    task = storage.create_task(
        workflow["id"],
        "Use designer",
        kind="design",
        profile="designer",
        prompt_text="Do the work.",
    )
    fake_hermes = tmp_path / "fake_hermes.py"
    fake_hermes.write_text(
        "from pathlib import Path\n"
        "Path('hermes_invoked.txt').write_text('unexpected', encoding='utf-8')\n",
        encoding="utf-8",
    )
    config = HWEConfig(
        profiles={
            "designer": {
                "hermes_command": f"python3 {fake_hermes}",
                "healthcheck": {
                    "url": "http://127.0.0.1:1/v1/chat/completions",
                    "model": "slow-model",
                    "retries": 2,
                    "retry_delay_seconds": 0,
                    "timeout_seconds": 0.1,
                },
            }
        }
    )

    summary = ProjectRuntime(storage, config=config).run_workitem(project["id"], workitem["id"])

    assert summary.tasks_started == 1
    assert summary.tasks_failed == 1
    assert storage.get_task(task["id"])["status"] == "failed"
    run = storage.list_task_runs(task_id=task["id"])[0]
    assert run["status"] == "failed"
    stderr_text = Path(run["stderr_path"]).read_text(encoding="utf-8")
    assert "Healthcheck attempt 1/2" in stderr_text
    assert "Healthcheck attempt 2/2" in stderr_text
    assert "Model healthcheck failed" in stderr_text
    assert not (project_root / "hermes_invoked.txt").exists()


def test_project_runtime_closes_agent_stdin_by_default(tmp_path: Path) -> None:
    project_root = tmp_path / "closed-stdin-runtime"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("closed-stdin-runtime")
    workitem = storage.create_workitem(project["id"], "Interactive prompt should not hang")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    task = storage.create_task(
        workflow["id"],
        "Use coder",
        kind="design",
        profile="coder",
        prompt_text="Do the work.",
    )
    fake_hermes = tmp_path / "fake_hermes.py"
    fake_hermes.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path('stdin_text.txt').write_text(sys.stdin.read(), encoding='utf-8')\n"
        "print('done')\n",
        encoding="utf-8",
    )
    config = HWEConfig(profiles={"coder": {"hermes_command": f"python3 {fake_hermes}", "timeout_seconds": 5}})

    summary = ProjectRuntime(storage, config=config).run_workitem(project["id"], workitem["id"])

    assert summary.tasks_started == 1
    assert summary.tasks_succeeded == 1
    assert storage.get_task(task["id"])["status"] == "succeeded"
    assert (project_root / "stdin_text.txt").read_text(encoding="utf-8") == ""


def test_project_runtime_turns_clarify_timeout_into_human_action(tmp_path: Path) -> None:
    project_root = tmp_path / "clarify-timeout-runtime"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("clarify-timeout-runtime")
    workitem = storage.create_workitem(project["id"], "Clarify timeout should wait")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="designer")
    task = storage.create_task(
        workflow["id"],
        "Break down plan",
        kind="planning",
        profile="designer",
        prompt_text="Create tasks.",
    )
    fake_hermes = tmp_path / "fake_hermes.py"
    fake_hermes.write_text(
        "import sys, time\n"
        "print('(clarify timed out after 120s — agent will decide)', flush=True)\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    config = HWEConfig(profiles={"designer": {"hermes_command": f"python3 {fake_hermes}", "timeout_seconds": 1}})

    summary = ProjectRuntime(storage, config=config).run_workitem(project["id"], workitem["id"])

    assert summary.tasks_started == 1
    assert summary.tasks_failed == 0
    assert summary.waiting_for_human == 1
    task_after = storage.get_task(task["id"])
    assert task_after["status"] == "waiting_for_info"
    run = storage.list_task_runs(task_id=task["id"])[0]
    assert run["status"] == "waiting_for_info"
    clarification_path = Path(run["stdout_path"]).parent / "clarification.md"
    assert clarification_path.exists()
    clarification_text = clarification_path.read_text(encoding="utf-8")
    assert "Hermes Clarification Timeout" in clarification_text
    actions = storage.list_human_actions(project["id"], status="pending")
    assert len(actions) == 1
    action = actions[0]
    assert action["kind"] == "info_request"
    assert action["run_id"] == run["id"]
    assert str(clarification_path) in action["body"]
    assert action["questions"][0]["id"] == "clarify-timeout"


def test_project_runtime_failure_releases_claim_on_unhandled_exception(tmp_path: Path) -> None:
    project_root = tmp_path / "runtime-exception-release"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("runtime-exception-release")
    workitem = storage.create_workitem(project["id"], "Missing template should fail cleanly")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="designer")
    task = storage.create_task(
        workflow["id"],
        "Use missing template",
        kind="design",
        profile="designer",
        prompt_template_ref="designer/does-not-exist",
        prompt_text="This should fail before Hermes is invoked.",
    )

    summary = ProjectRuntime(storage, config=HWEConfig()).run_workitem(project["id"], workitem["id"], max_tasks=1)

    assert summary.tasks_started == 1
    assert summary.tasks_failed == 1
    task_after = storage.get_task(task["id"])
    assert task_after["status"] == "failed"
    runs = storage.list_task_runs(task_id=task["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["result"]["error"] == "runtime_exception"
    stderr_text = Path(runs[0]["stderr_path"]).read_text(encoding="utf-8")
    assert "Unhandled HWE task runtime exception" in stderr_text
    assert "Prompt template not found" in stderr_text
    with storage.connect() as connection:
        claim_row = connection.execute("SELECT status, release_reason FROM worker_claims WHERE task_id=?", (task["id"],)).fetchone()
    assert claim_row["status"] == "released"
    assert claim_row["release_reason"] == "failed"
