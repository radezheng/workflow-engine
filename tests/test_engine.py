from __future__ import annotations

from pathlib import Path

import yaml

from hermes_workflow_engine.config import HWEConfig, default_config_path
from hermes_workflow_engine.runtime import WorkflowRuntime
from hermes_workflow_engine.spec import load_workflow
from hermes_workflow_engine.storage import Storage
from hermes_workflow_engine.worker import WorkerAdapter


def test_command_step_runs_and_records_state(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "noop.md").write_text("No-op prompt", encoding="utf-8")
    workflow_path = tmp_path / "workflow.yaml"
    workflow = {
        "workflow": {"id": "test-flow", "workspace": str(workspace)},
        "profiles": {"coder": {"hermes_profile": "coder"}},
        "steps": [
            {
                "id": "init",
                "title": "Init",
                "kind": "command",
                "commands": ["git init", "mkdir -p src", "python3 -c \"from pathlib import Path; Path('src/example.py').write_text('def hello():\\n    return \\\"hi\\\"\\n', encoding='utf-8')\""],
                "outputs": ["src/example.py"],
                "gates": ["git_initialized", "python_syntax_ok", "no_hardcoded_credentials"],
            },
            {
                "id": "agent",
                "title": "Agent",
                "kind": "agent",
                "profile": "coder",
                "needs": ["init"],
                "prompt": "prompts/noop.md",
                "outputs": ["src/example.py"],
                "review": {"mode": "none", "gates": ["python_syntax_ok"]},
            },
        ],
    }
    workflow_path.write_text(yaml.safe_dump(workflow), encoding="utf-8")

    spec = load_workflow(workflow_path)
    storage = Storage(spec.engine_dir)
    runtime = WorkflowRuntime(spec, storage, dry_run=True)
    summary = runtime.run()

    assert summary.steps_failed == 0
    assert [row["state"] for row in storage.list_steps(spec.id)] == ["completed", "completed"]
    assert (workspace / ".engine" / "engine.db").exists()
    assert list((workspace / ".engine" / "context").glob("ctx_agent_*.md"))


def test_project_folder_gets_own_engine_state(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    workflow_path = tmp_path / "workflow.yaml"
    workflow = {
        "workflow": {"id": "project-flow", "workspace": str(workspace_root), "project": "projects/alpha"},
        "steps": [
            {
                "id": "init",
                "kind": "command",
                "commands": ["git init", "mkdir -p src", "python3 -c \"from pathlib import Path; Path('src/alpha.py').write_text('VALUE = 1\\n', encoding='utf-8')\""],
                "outputs": ["src/alpha.py"],
                "gates": ["git_initialized", "python_syntax_ok"],
            }
        ],
    }
    workflow_path.write_text(yaml.safe_dump(workflow), encoding="utf-8")

    spec = load_workflow(workflow_path)
    storage = Storage(spec.engine_dir)
    runtime = WorkflowRuntime(spec, storage, dry_run=True)
    summary = runtime.run()

    project_workspace = workspace_root / "projects" / "alpha"
    assert summary.steps_failed == 0
    assert spec.workspace_root == workspace_root
    assert spec.workspace == project_workspace
    assert spec.engine_dir == project_workspace / ".engine"
    assert (project_workspace / "src" / "alpha.py").exists()
    assert (project_workspace / ".engine" / "engine.db").exists()
    assert not (workspace_root / ".engine").exists()


def test_config_default_workspace_root_is_used_when_spec_omits_workspace(tmp_path: Path) -> None:
    workspace_root = tmp_path / "configured-workspace"
    workflow_path = tmp_path / "workflow.yaml"
    workflow = {
        "workflow": {"id": "configured-flow", "project": "alpha"},
        "steps": [{"id": "init", "kind": "command", "commands": ["true"]}],
    }
    workflow_path.write_text(yaml.safe_dump(workflow), encoding="utf-8")

    spec = load_workflow(workflow_path, config=HWEConfig(default_workspace_root=workspace_root))

    assert spec.workspace_root == workspace_root
    assert spec.workspace == workspace_root / "alpha"


def test_default_config_path_walks_up_to_project_local_file(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "repo"
    nested = project_root / "subdir" / "child"
    nested.mkdir(parents=True)
    config_path = project_root / "hwe.config.yaml"
    config_path.write_text("default_workspace_root: /tmp/hermes-projects\n", encoding="utf-8")

    monkeypatch.chdir(nested)

    assert default_config_path() == config_path


def test_hermes_profile_command_uses_current_cli_shape(tmp_path: Path) -> None:
    workflow_path = tmp_path / "workflow.yaml"
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("Do the work", encoding="utf-8")
    workflow = {
        "workflow": {"id": "test-flow", "workspace": str(tmp_path / "workspace")},
        "profiles": {"coder": {"hermes_profile": "coder", "hermes_command": "fake-hermes", "hermes_args": ["--accept-hooks"]}},
        "steps": [{"id": "agent", "kind": "agent", "profile": "coder", "prompt": str(prompt_path)}],
    }
    workflow_path.write_text(yaml.safe_dump(workflow), encoding="utf-8")

    spec = load_workflow(workflow_path)
    adapter = WorkerAdapter(spec)
    command = adapter.hermes_command_preview("coder", "hello")

    assert command == ["fake-hermes", "chat", "-Q", "--source", "workflow-engine", "--accept-hooks", "-q", "hello"]


def test_removed_steps_are_not_reported_in_status(tmp_path: Path) -> None:
    workflow_path = tmp_path / "workflow.yaml"
    workflow = {
        "workflow": {"id": "stale-flow", "workspace": str(tmp_path / "workspace")},
        "steps": [
            {"id": "old", "kind": "command", "commands": ["true"]},
            {"id": "current", "kind": "command", "commands": ["true"], "needs": ["old"]},
        ],
    }
    workflow_path.write_text(yaml.safe_dump(workflow), encoding="utf-8")
    spec = load_workflow(workflow_path)
    storage = Storage(spec.engine_dir)
    WorkflowRuntime(spec, storage, dry_run=True).load()

    workflow["steps"] = [{"id": "current", "kind": "command", "commands": ["true"]}]
    workflow_path.write_text(yaml.safe_dump(workflow), encoding="utf-8")
    updated_spec = load_workflow(workflow_path)
    WorkflowRuntime(updated_spec, storage, dry_run=True).load()

    assert [row["id"] for row in storage.list_steps(updated_spec.id)] == ["current"]