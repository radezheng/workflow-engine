from __future__ import annotations

import json
from pathlib import Path

from hermes_workflow_engine.cli import main
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
