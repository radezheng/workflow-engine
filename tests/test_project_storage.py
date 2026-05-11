from __future__ import annotations

import json
from pathlib import Path

from hermes_workflow_engine.cli import main
from hermes_workflow_engine.config import HWEConfig
from hermes_workflow_engine.project_runtime import ProjectRuntime
from hermes_workflow_engine.project_storage import ProjectStorage


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
    template = storage.create_role_prompt_template(
        project["id"],
        "reviewer",
        "implementation-review",
        "Check correctness, tests, security, and regression risk.",
        description="Default reviewer best practices",
        tags=["review", "best-practices"],
    )
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    first_task = storage.create_task(
        workflow["id"],
        "Design notes",
        kind="design",
        profile="reviewer",
        skills=["hermes-project-workflow"],
        prompt_template_id=template["id"],
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
    assert first_task["prompt_template_id"] == template["id"]
    assert second_task["status"] == "pending"
    assert storage.list_role_prompt_templates(project["id"], role="reviewer")[0]["tags"] == ["review", "best-practices"]

    claimed = storage.claim_next_task(workflow["id"], worker_id="worker-1", profile="reviewer")
    assert claimed is not None
    assert claimed["id"] == first_task["id"]
    assert claimed["status"] == "claimed"
    assert claimed["attempt"] == 1
    assert claimed["claim_id"].startswith("claim_")

    completed = storage.complete_task(first_task["id"])
    assert completed["status"] == "succeeded"

    tasks = {task["id"]: task for task in storage.list_tasks(workflow["id"])}
    assert tasks[first_task["id"]]["status"] == "succeeded"
    assert tasks[second_task["id"]]["status"] == "ready"
    assert tasks[second_task["id"]]["outputs"] == ["backend/notes.py"]
    assert tasks[second_task["id"]]["gates"] == ["python_syntax_ok"]

    events = storage.list_events(project["id"])
    event_types = [event["type"] for event in events]
    assert "project_upserted" in event_types
    assert "task_ready" in event_types
    assert "task_completed" in event_types
    assert (project_root / ".engine" / "engine.db").exists()


def test_project_init_cli_writes_project_database(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "cli-project"

    exit_code = main(["project", "init", str(project_root), "--id", "cli", "--name", "CLI Project"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "cli"
    assert payload["name"] == "CLI Project"
    assert payload["root_path"] == str(project_root.resolve())
    assert (project_root / ".engine" / "engine.db").exists()


def test_prompt_template_cli_creates_template(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "template-project"
    assert main(["project", "init", str(project_root), "--id", "template-project"]) == 0
    capsys.readouterr()

    exit_code = main(
        [
            "prompt-template",
            "create",
            str(project_root),
            "reviewer",
            "qa-review",
            "--project-id",
            "template-project",
            "--body",
            "Reject missing tests and unsafe changes.",
            "--tag",
            "qa",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["role"] == "reviewer"
    assert payload["name"] == "qa-review"
    assert payload["body_md"] == "Reject missing tests and unsafe changes."
    assert payload["tags"] == ["qa"]


def test_prompt_template_cli_uses_hwe_template_root(tmp_path: Path, capsys, monkeypatch) -> None:
    hwe_root = tmp_path / "hwe"
    template_root = hwe_root / "ptemplate"
    template_dir = template_root / "reviewer"
    template_dir.mkdir(parents=True)
    (template_dir / "qa-review.md").write_text("Review for correctness and regression risk.", encoding="utf-8")
    (hwe_root / "hwe.config.yaml").write_text("prompt_template_root: ./ptemplate\n", encoding="utf-8")
    monkeypatch.chdir(hwe_root)

    project_root = tmp_path / "template-project"
    assert main(["project", "init", str(project_root), "--id", "template-project"]) == 0
    capsys.readouterr()

    exit_code = main(
        [
            "prompt-template",
            "create",
            str(project_root),
            "reviewer",
            "qa-review",
            "--project-id",
            "template-project",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["body_md"] == "Review for correctness and regression risk."


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


def test_run_workitem_cli_dry_run_agent_writes_prompt(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "agent-runtime"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("agent-runtime")
    workitem = storage.create_workitem(project["id"], "Design notes", requirements="Support Markdown notes.", constraints="Keep existing behavior.")
    template = storage.create_role_prompt_template(project["id"], "reviewer", "design-review", "Review design scope carefully.")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    task = storage.create_task(
        workflow["id"],
        "Draft design",
        kind="design",
        profile="reviewer",
        prompt_template_id=template["id"],
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
