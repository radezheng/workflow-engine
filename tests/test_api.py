from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from hermes_workflow_engine.api import app
from hermes_workflow_engine.project_storage import ProjectStorage


def test_api_lists_ai_providers_and_assists(tmp_path: Path, monkeypatch) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config_path = tmp_path / "hwe.config.yaml"
    config_path.write_text(
        f"""
default_workspace_root: {workspace_root}
ai_providers:
  local-lms:
    type: openai_compatible
    base_url: http://127.0.0.1:1234/v1
    model: local-model
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HWE_CONFIG", str(config_path))

    def fake_assist(config, *, provider_name, target, messages, draft, context):
        _ = config, draft, context
        assert provider_name == "local-lms"
        assert target == "project"
        assert messages[-1]["content"] == "Make a notes app project"
        return {"message": "Filled project draft.", "draft": {"name": "Notes App", "project_ref": "notes-app"}, "raw": "{}"}

    monkeypatch.setattr("hermes_workflow_engine.api.create_ai_assist_response", fake_assist)
    client = TestClient(app)

    providers = client.get("/api/ai/providers")
    assert providers.status_code == 200
    assert providers.json() == [
        {"name": "local-lms", "type": "openai_compatible", "base_url": "http://127.0.0.1:1234/v1", "model": "local-model", "has_api_key": False}
    ]

    assisted = client.post(
        "/api/ai/assist",
        json={"provider": "local-lms", "target": "project", "messages": [{"role": "user", "content": "Make a notes app project"}], "draft": {}},
    )
    assert assisted.status_code == 200
    assert assisted.json()["draft"]["project_ref"] == "notes-app"


def test_api_workitem_ai_assist_includes_project_context(tmp_path: Path, monkeypatch) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config_path = tmp_path / "hwe.config.yaml"
    config_path.write_text(
        f"""
default_workspace_root: {workspace_root}
ai_providers:
  local-lms:
    type: openai_compatible
    base_url: http://127.0.0.1:1234/v1
    model: local-model
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HWE_CONFIG", str(config_path))

    storage = ProjectStorage(workspace_root / "gamma")
    storage.initialize()
    storage.upsert_project("Gamma Project", project_id="gamma")
    workitem = storage.create_workitem(
        "gamma",
        "Build dashboard",
        requirements="Show active work and task health.",
        constraints="Keep it local-first.",
        acceptance=["Dashboard opens"],
    )
    workflow = storage.create_workflow("gamma", workitem["id"], planner_profile="designer")
    storage.create_task(workflow["id"], "Implement dashboard shell", kind="agent", profile="coder")

    captured_context: dict[str, Any] = {}

    def fake_assist(config, *, provider_name, target, messages, draft, context):
        _ = config, provider_name, messages, draft
        assert target == "workitem"
        captured_context.update(context)
        return {"message": "Filled workitem draft.", "draft": {"title": "Add dashboard filters"}, "ready": True, "raw": "{}"}

    monkeypatch.setattr("hermes_workflow_engine.api.create_ai_assist_response", fake_assist)

    response = TestClient(app).post(
        "/api/ai/assist",
        json={
            "provider": "local-lms",
            "target": "workitem",
            "messages": [{"role": "user", "content": "Add the next useful dashboard feature"}],
            "draft": {"type": "feature"},
            "context": {"project_ref": "gamma", "project_id": "gamma"},
        },
    )

    assert response.status_code == 200
    assert captured_context["project"] == {"id": "gamma", "name": "Gamma Project", "status": "active"}
    existing_workitem = captured_context["existing_workitems"][0]
    assert existing_workitem["title"] == "Build dashboard"
    assert existing_workitem["requirements"] == "Show active work and task health."
    assert existing_workitem["current_workflow"]["task_status_counts"] == {"ready": 1}
    assert existing_workitem["current_workflow"]["tasks"][0]["title"] == "Implement dashboard shell"


def test_api_config_reports_project_database_without_password(tmp_path: Path, monkeypatch) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config_path = tmp_path / "hwe.config.yaml"
    config_path.write_text(
        f"""
default_workspace_root: {workspace_root}
project_database:
  backend: postgres
  host: 127.0.0.1
  port: 5432
  database: hindsight_db
  user: hindsight_user
  schema: hwe
  maxconn: 8
  password: super-secret
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HWE_CONFIG", str(config_path))

    response = TestClient(app).get("/api/config")

    assert response.status_code == 200
    project_database = response.json()["project_database"]
    assert project_database == {
        "backend": "postgres",
        "host": "127.0.0.1",
        "port": 5432,
        "database": "hindsight_db",
        "user": "hindsight_user",
        "schema": "hwe",
        "maxconn": 8,
        "has_password": True,
    }
    assert "super-secret" not in response.text


def test_api_creates_project_and_workitem(tmp_path: Path, monkeypatch) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config_path = tmp_path / "hwe.config.yaml"
    config_path.write_text(f"default_workspace_root: {workspace_root}\n", encoding="utf-8")
    monkeypatch.setenv("HWE_CONFIG", str(config_path))

    client = TestClient(app)

    project = client.post("/api/projects", json={"name": "Gamma Project", "project_ref": "gamma"})
    assert project.status_code == 200
    assert project.json()["id"] == "gamma"
    assert project.json()["name"] == "Gamma Project"
    assert (workspace_root / "gamma" / ".engine" / "engine.db").exists()

    workitem = client.post(
        "/api/projects/gamma/workitems",
        json={
            "project_id": "gamma",
            "title": "Build dashboard",
            "type": "feature",
            "requirements": "Show active work.",
            "constraints": "Keep it local.",
            "acceptance": ["Dashboard opens", "Workitems are visible"],
            "priority": 20,
            "risk_level": "low",
        },
    )
    assert workitem.status_code == 200
    assert workitem.json()["title"] == "Build dashboard"
    assert workitem.json()["priority"] == 20

    workitems = client.get("/api/projects/gamma/workitems", params={"project_id": "gamma"})
    assert workitems.status_code == 200
    assert workitems.json()[0]["id"] == workitem.json()["id"]

    archived = client.post("/api/projects/gamma/archive", params={"project_id": "gamma"})
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    active_projects = client.get("/api/projects")
    assert active_projects.status_code == 200
    assert active_projects.json()["projects"] == []

    all_projects = client.get("/api/projects", params={"include_archived": "true"})
    assert all_projects.status_code == 200
    assert all_projects.json()["projects"][0]["id"] == "gamma"
    assert all_projects.json()["projects"][0]["status"] == "archived"

    restored = client.post("/api/projects/gamma/restore", params={"project_id": "gamma"})
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"


def test_api_plans_workitem_by_creating_workflow_and_designer_task(tmp_path: Path, monkeypatch) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    template_root = tmp_path / "ptemplate"
    designer_root = template_root / "designer"
    designer_root.mkdir(parents=True)
    (designer_root / "workitem-plan.md").write_text("Plan this workitem.", encoding="utf-8")
    (designer_root / "task-breakdown.md").write_text("Break down tasks.", encoding="utf-8")
    config_path = tmp_path / "hwe.config.yaml"
    config_path.write_text(
        f"""
default_workspace_root: {workspace_root}
prompt_template_root: {template_root}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HWE_CONFIG", str(config_path))

    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "Planner Project", "project_ref": "planner-project"})
    assert project.status_code == 200
    workitem = client.post("/api/projects/planner-project/workitems", json={"project_id": "planner-project", "title": "Add search", "risk_level": "low"})
    assert workitem.status_code == 200

    planned = client.post(f"/api/projects/planner-project/workitems/{workitem.json()['id']}/plan", json={"project_id": "planner-project"})

    assert planned.status_code == 200
    payload = planned.json()
    assert payload["workflow"]["workitem_id"] == workitem.json()["id"]
    assert payload["task"]["status"] == "ready"
    assert payload["task"]["profile"] == "designer"
    assert payload["task"]["prompt_template_ref"] == "designer/workitem-plan"

    planned_again = client.post(f"/api/projects/planner-project/workitems/{workitem.json()['id']}/plan", json={"project_id": "planner-project"})
    assert planned_again.status_code == 200
    assert len(planned_again.json()["tasks"]) == 1

    custom_workitem = client.post("/api/projects/planner-project/workitems", json={"project_id": "planner-project", "title": "Refine search", "risk_level": "low"})
    assert custom_workitem.status_code == 200
    custom_plan = client.post(
        f"/api/projects/planner-project/workitems/{custom_workitem.json()['id']}/plan",
        json={"project_id": "planner-project", "prompt_template_ref": "designer/task-breakdown"},
    )
    assert custom_plan.status_code == 200
    assert custom_plan.json()["task"]["prompt_template_ref"] == "designer/task-breakdown"


def test_api_materializes_plan_output_into_breakdown_task(tmp_path: Path, monkeypatch) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    template_root = tmp_path / "ptemplate"
    (template_root / "designer").mkdir(parents=True)
    (template_root / "designer" / "task-breakdown.md").write_text("Break down this plan.", encoding="utf-8")
    config_path = tmp_path / "hwe.config.yaml"
    config_path.write_text(
        f"""
default_workspace_root: {workspace_root}
prompt_template_root: {template_root}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HWE_CONFIG", str(config_path))

    project_root = workspace_root / "materialize-project"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("materialize-project", project_id="materialize-project")
    workitem = storage.create_workitem(project["id"], "Build todo")
    workflow = storage.create_workflow(project["id"], workitem["id"])
    task = storage.create_task(workflow["id"], "Plan workitem", kind="planning", profile="designer")
    storage.claim_next_task(workflow["id"], worker_id="test", profile="designer")
    run = storage.create_task_run(task["id"], profile="designer")
    run_dir = project_root / ".engine" / "runs" / run["id"]
    run_dir.mkdir(parents=True)
    stdout_path = run_dir / "stdout.log"
    stdout_path.write_text(
        """
| Task ID | Role | Kind | Dependencies | Description | Expected Output | Gate/Verification |
|---|---|---|---|---|---|---|
| **T1** | Coder | implementation | None | Backend API | main.py | pytest passes |
| **T2** | Coder | implementation | T1 | Frontend UI | src/App.tsx | npm build passes |
| **T3** | QA | test | T2 | QA smoke | report | smoke passes |
""",
        encoding="utf-8",
    )
    storage.finish_task_run(run["id"], status="succeeded", exit_code=0, result={"profile": "designer"}, stdout_path=stdout_path)
    storage.complete_task(task["id"], status="succeeded", result={"run_id": run["id"]})

    client = TestClient(app)
    prompt_text = f"Read this plan and create HWE tasks.\nPlan stdout path: {stdout_path}"
    response = client.post(
        f"/api/projects/materialize-project/tasks/{task['id']}/materialize-plan",
        json={"project_id": "materialize-project", "prompt_template_ref": "designer/task-breakdown", "prompt_text": prompt_text},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["created"]) == 1
    created = payload["created"][0]
    assert created["title"] == "Break down plan into executable tasks"
    assert created["kind"] == "planning"
    assert created["profile"] == "designer"
    assert created["prompt_template_ref"] == "designer/task-breakdown"
    assert created["prompt_text"] == prompt_text

    repeated = client.post(f"/api/projects/materialize-project/tasks/{task['id']}/materialize-plan", json={"project_id": "materialize-project"})
    assert repeated.status_code == 200
    assert repeated.json()["created"] == []
    assert repeated.json()["skipped"][0]["id"] == created["id"]


def test_api_creates_and_lists_prompt_templates(tmp_path: Path, monkeypatch) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    template_root = tmp_path / "ptemplate"
    template_role = template_root / "reviewer"
    template_role.mkdir(parents=True)
    template_file = template_role / "implementation-review.md"
    template_file.write_text("# Review\n\nCheck the implementation.", encoding="utf-8")
    config_path = tmp_path / "hwe.config.yaml"
    config_path.write_text(
        f"""
default_workspace_root: {workspace_root}
prompt_template_root: {template_root}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HWE_CONFIG", str(config_path))

    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "Delta", "project_ref": "delta"})
    assert project.status_code == 200

    public_templates = client.get("/api/prompt-templates")
    assert public_templates.status_code == 200
    assert public_templates.json()[0]["source"] == "public"
    assert public_templates.json()[0]["body_md"] == "# Review\n\nCheck the implementation."

    created = client.post(
        "/api/projects/delta/prompt-templates",
        json={"project_id": "delta", "role": "reviewer", "name": "implementation-review", "description": "Review prompt", "tags": ["review"]},
    )
    assert created.status_code == 200
    assert created.json()["source"] == "project"
    assert created.json()["body_md"] == "# Review\n\nCheck the implementation."
    assert (workspace_root / "delta" / ".engine" / "prompt-templates" / "reviewer" / "implementation-review.md").exists()

    custom = client.post(
        "/api/projects/delta/prompt-templates",
        json={"project_id": "delta", "role": "coder", "name": "custom", "body": "Write code.", "tags": ["impl"]},
    )
    assert custom.status_code == 200
    assert custom.json()["body_md"] == "Write code."

    published = client.post("/api/prompt-templates", json={"role": "qa", "name": "smoke", "body": "Run smoke checks."})
    assert published.status_code == 200
    assert published.json()["source"] == "public"
    assert (template_root / "qa" / "smoke.md").read_text(encoding="utf-8") == "Run smoke checks."

    templates = client.get("/api/projects/delta/prompt-templates", params={"project_id": "delta"})
    assert templates.status_code == 200
    template_keys = {(template["source"], template["role"], template["name"]) for template in templates.json()}
    assert ("project", "coder", "custom") in template_keys
    assert ("project", "reviewer", "implementation-review") in template_keys
    assert ("public", "qa", "smoke") in template_keys

    deleted_project = client.delete("/api/projects/delta/prompt-templates/coder/custom", params={"project_id": "delta"})
    assert deleted_project.status_code == 200
    assert not (workspace_root / "delta" / ".engine" / "prompt-templates" / "coder" / "custom.md").exists()

    deleted_public = client.delete("/api/prompt-templates/qa/smoke")
    assert deleted_public.status_code == 200
    assert not (template_root / "qa" / "smoke.md").exists()


def test_api_previews_rendered_prompt_and_updates_unrun_task(tmp_path: Path, monkeypatch) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    template_root = tmp_path / "ptemplate"
    (template_root / "coder").mkdir(parents=True)
    (template_root / "coder" / "implementation-slice.md").write_text("# Implement\n\nUse the template.", encoding="utf-8")
    (template_root / "reviewer").mkdir(parents=True)
    (template_root / "reviewer" / "implementation-review.md").write_text("# Review\n\nCheck the work.", encoding="utf-8")
    config_path = tmp_path / "hwe.config.yaml"
    config_path.write_text(
        f"""
default_workspace_root: {workspace_root}
prompt_template_root: {template_root}
profiles:
  coder: {{}}
  reviewer: {{}}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HWE_CONFIG", str(config_path))

    project_root = workspace_root / "edit-task"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("edit-task", project_id="edit-task")
    workitem = storage.create_workitem(project["id"], "Edit prompt", requirements="Use the chosen template.")
    workflow = storage.create_workflow(project["id"], workitem["id"])
    task = storage.create_task(
        workflow["id"],
        "Implement slice",
        kind="implementation",
        profile="coder",
        prompt_template_ref="coder/implementation-slice",
        prompt_text="Do the focused slice.",
    )

    client = TestClient(app)
    preview = client.get(f"/api/projects/edit-task/tasks/{task['id']}/prompt-preview", params={"project_id": "edit-task"})
    assert preview.status_code == 200
    assert "# Implement" in preview.json()["text"]
    assert "Do the focused slice." in preview.json()["text"]
    assert "Profile:" not in preview.json()["text"]

    updated = client.patch(
        f"/api/projects/edit-task/tasks/{task['id']}",
        json={"project_id": "edit-task", "profile": "reviewer", "prompt_template_ref": "reviewer/implementation-review", "prompt_text": "Review before coding."},
    )
    assert updated.status_code == 200
    assert updated.json()["profile"] == "reviewer"
    assert updated.json()["prompt_template_ref"] == "reviewer/implementation-review"

    storage.claim_next_task(workflow["id"], worker_id="test", profile="reviewer")
    run = storage.create_task_run(task["id"], profile="reviewer")
    storage.finish_task_run(run["id"], status="succeeded", exit_code=0, result={})
    storage.complete_task(task["id"], status="succeeded")
    blocked = client.patch(
        f"/api/projects/edit-task/tasks/{task['id']}",
        json={"project_id": "edit-task", "profile": "coder", "prompt_template_ref": "coder/implementation-slice"},
    )
    assert blocked.status_code == 400


def test_api_lists_project_dashboard_and_runs_command_task(tmp_path: Path, monkeypatch) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config_path = tmp_path / "hwe.config.yaml"
    config_path.write_text(f"default_workspace_root: {workspace_root}\n", encoding="utf-8")
    monkeypatch.setenv("HWE_CONFIG", str(config_path))

    project_root = workspace_root / "alpha"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("alpha", project_id="alpha")
    workitem = storage.create_workitem(project["id"], "Create marker")
    workflow = storage.create_workflow(project["id"], workitem["id"], planner_profile="reviewer")
    task = storage.create_task(
        workflow["id"],
        "Write marker",
        kind="command",
        profile="command",
        prompt_text="python3 -c \"from pathlib import Path; Path('marker.txt').write_text('ok', encoding='utf-8')\"",
    )

    client = TestClient(app)

    projects = client.get("/api/projects")
    assert projects.status_code == 200
    assert projects.json()["projects"][0]["id"] == "alpha"

    dashboard = client.get(f"/api/projects/alpha/workitems/{workitem['id']}/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["tasks"][0]["id"] == task["id"]

    run = client.post(f"/api/projects/alpha/workitems/{workitem['id']}/run", json={"max_tasks": 1})
    assert run.status_code == 200
    assert run.json()["tasks_succeeded"] == 1
    assert (project_root / "marker.txt").read_text(encoding="utf-8") == "ok"

    runs = client.get(f"/api/projects/alpha/tasks/{task['id']}/runs")
    assert runs.status_code == 200
    run_id = runs.json()[0]["id"]
    logs = client.get(f"/api/projects/alpha/runs/{run_id}/logs", params={"stream": "stdout"})
    assert logs.status_code == 200
    assert logs.json()["stream"] == "stdout"


def test_api_task_retry_release_and_human_action_resolution(tmp_path: Path, monkeypatch) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    config_path = tmp_path / "hwe.config.yaml"
    config_path.write_text(f"default_workspace_root: {workspace_root}\n", encoding="utf-8")
    monkeypatch.setenv("HWE_CONFIG", str(config_path))

    project_root = workspace_root / "beta"
    storage = ProjectStorage(project_root)
    project = storage.upsert_project("beta", project_id="beta")
    workitem = storage.create_workitem(project["id"], "Human approval")
    workflow = storage.create_workflow(project["id"], workitem["id"])
    task = storage.create_task(workflow["id"], "Approve", kind="approval", profile="reviewer")
    storage.claim_next_task(workflow["id"], worker_id="test", profile="reviewer")
    action = storage.complete_task(
        task["id"],
        status="waiting_for_info",
        human_action_title="Need answer",
        human_action_body="Pick one",
        questions=[{"id": "q1", "question": "Which option?"}],
    )["human_action"]

    client = TestClient(app)

    actions = client.get("/api/projects/beta/human-actions", params={"status": "pending"})
    assert actions.status_code == 200
    assert actions.json()[0]["id"] == action["id"]

    answered = client.post(f"/api/projects/beta/human-actions/{action['id']}/answer", json={"text": "Use option A", "by": "tester"})
    assert answered.status_code == 200
    assert answered.json()["status"] == "answered"
    assert storage.get_task(task["id"])["status"] == "ready"

    claimed = storage.claim_next_task(workflow["id"], worker_id="test-2", profile="reviewer")
    assert claimed is not None
    released = client.post(f"/api/projects/beta/tasks/{task['id']}/release", json={"reason": "test-release"})
    assert released.status_code == 200
    assert released.json()["status"] == "ready"

    storage.complete_task(task["id"], status="failed", result={"error": "transient"})
    retried = client.post(f"/api/projects/beta/tasks/{task['id']}/retry", json={"reason": "test-retry"})
    assert retried.status_code == 200
    assert retried.json()["status"] == "ready"

    completed = client.post(f"/api/projects/beta/tasks/{task['id']}/complete", json={"status": "superseded", "result": {"reason": "covered"}})
    assert completed.status_code == 200
    assert completed.json()["status"] == "superseded"