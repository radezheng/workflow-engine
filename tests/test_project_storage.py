from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from hermes_workflow_engine.cli import main
from hermes_workflow_engine.config import HWEConfig
from hermes_workflow_engine.project_runtime import ProjectRuntime
from hermes_workflow_engine.project_storage import ProjectStorage


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

    claimed = storage.claim_next_task(workflow["id"], worker_id="worker-1", profile="reviewer")
    assert claimed is not None
    assert claimed["id"] == first_task["id"]
    assert claimed["status"] == "claimed"
    assert claimed["attempt"] == 1
    assert claimed["claim_id"].startswith("claim_")
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
        prompt_text="python3 -c \"from pathlib import Path; Path('marker.txt').write_text('ok', encoding='utf-8')\"",
        outputs=["marker.txt"],
    )

    summary = ProjectRuntime(storage).run_workitem(project["id"], workitem["id"])

    assert summary.tasks_started == 1
    assert summary.tasks_succeeded == 1
    assert summary.blocked == []
    assert (project_root / "marker.txt").read_text(encoding="utf-8") == "ok"
    assert storage.get_task(task["id"])["status"] == "succeeded"
    run = storage.list_task_runs(task_id=task["id"])[0]
    assert Path(run["stdout_path"]).exists()
    assert Path(run["stderr_path"]).exists()
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


def test_task_release_cli_returns_claimed_task_to_ready(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "release-project"
    assert main(["project", "init", str(project_root), "--id", "release-project"]) == 0
    capsys.readouterr()
    assert main(["workitem", "create", str(project_root), "Release claim", "--project-id", "release-project"]) == 0
    workitem = json.loads(capsys.readouterr().out)
    assert main(["workflow", "create", str(project_root), workitem["id"], "--project-id", "release-project"]) == 0
    workflow = json.loads(capsys.readouterr().out)
    assert main(["task", "create", str(project_root), workflow["id"], "Claim me", "--kind", "design", "--profile", "reviewer"]) == 0
    task = json.loads(capsys.readouterr().out)
    assert main(["task", "claim", str(project_root), workflow["id"], "--worker-id", "worker-1", "--profile", "reviewer"]) == 0
    capsys.readouterr()

    assert main(["task", "release", str(project_root), task["id"], "--reason", "cancelled-run"]) == 0
    released = json.loads(capsys.readouterr().out)

    assert released["status"] == "ready"
    assert main(["task", "claim", str(project_root), workflow["id"], "--worker-id", "worker-2", "--profile", "reviewer"]) == 0
    reclaimed = json.loads(capsys.readouterr().out)
    assert reclaimed["id"] == task["id"]


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
    reclaimed = json.loads(capsys.readouterr().out)
    assert reclaimed["id"] == task["id"]


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
    assert (project_root / "hermes_invoked.txt").read_text(encoding="utf-8").startswith("chat -Q --source workflow-engine")


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
