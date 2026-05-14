from __future__ import annotations

from pathlib import Path

import yaml

from hermes_workflow_engine import ai
from hermes_workflow_engine.ai import create_ai_assist_response
from hermes_workflow_engine.config import HWEConfig, default_config_path, load_config
from hermes_workflow_engine.project_storage import _postgres_connect_kwargs, _postgres_maxconn, _postgres_pool_key
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


def test_prompt_template_root_defaults_to_hwe_config_directory(tmp_path: Path, monkeypatch) -> None:
    hwe_root = tmp_path / "hwe"
    nested = hwe_root / "subdir"
    nested.mkdir(parents=True)
    config_path = hwe_root / "hwe.config.yaml"
    config_path.write_text("default_workspace_root: /tmp/hermes-projects\n", encoding="utf-8")

    monkeypatch.chdir(nested)
    config = load_config()

    assert config.prompt_template_root == hwe_root / "ptemplate"


def test_prompt_template_root_config_is_relative_to_hwe_config_directory(tmp_path: Path) -> None:
    hwe_root = tmp_path / "hwe"
    hwe_root.mkdir()
    config_path = hwe_root / "hwe.config.yaml"
    config_path.write_text("prompt_template_root: ./role-prompts\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.prompt_template_root == hwe_root / "role-prompts"


def test_hwe_config_loads_profile_preflight(tmp_path: Path) -> None:
    config_path = tmp_path / "hwe.config.yaml"
    config_path.write_text(
        """
profiles:
  coder:
    switch_command: lms unload --all
    hermes_command: coder
    hermes_args: [--accept-hooks]
    success_exit_codes: [0, -6]
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.profile_config("coder") == {
        "switch_command": "lms unload --all",
        "hermes_command": "coder",
        "hermes_args": ["--accept-hooks"],
        "success_exit_codes": [0, -6],
    }
    assert config.profile_config("reviewer") == {}


def test_hwe_config_loads_ai_providers(tmp_path: Path) -> None:
    config_path = tmp_path / "hwe.config.yaml"
    config_path.write_text(
        """
ai_providers:
  local-lms:
    type: openai_compatible
    base_url: http://127.0.0.1:1234/v1
    model: local-model
  openai:
    type: openai_compatible
    base_url: https://api.openai.com/v1
    model: gpt-test
    api_key_env: OPENAI_API_KEY
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.ai_providers == {
        "local-lms": {"type": "openai_compatible", "base_url": "http://127.0.0.1:1234/v1", "model": "local-model"},
        "openai": {"type": "openai_compatible", "base_url": "https://api.openai.com/v1", "model": "gpt-test", "api_key_env": "OPENAI_API_KEY"},
    }


def test_hwe_config_loads_postgres_project_database_with_local_password(tmp_path: Path) -> None:
    config_path = tmp_path / "hwe.config.yaml"
    config_path.write_text(
        """
project_database:
  backend: postgres
  host: 127.0.0.1
  port: 5432
  database: hindsight_db
  user: hindsight_user
  schema: hwe
  password: local-password
  gssencmode: disable
  maxconn: 8
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.project_database == {
        "backend": "postgres",
        "host": "127.0.0.1",
        "port": 5432,
        "database": "hindsight_db",
        "user": "hindsight_user",
        "schema": "hwe",
        "password": "local-password",
        "gssencmode": "disable",
        "maxconn": 8,
    }


def test_postgres_connect_kwargs_disable_gss_by_default() -> None:
    kwargs = _postgres_connect_kwargs(
        {
            "host": "127.0.0.1",
            "port": 5432,
            "database": "hindsight_db",
            "user": "hindsight_user",
            "password": "local-password",
        }
    )

    assert kwargs["gssencmode"] == "disable"
    assert kwargs["password"] == "local-password"
    assert "maxconn" not in kwargs


def test_postgres_pool_key_includes_maxconn() -> None:
    base_config = {
        "host": "127.0.0.1",
        "port": 5432,
        "database": "hindsight_db",
        "user": "hindsight_user",
        "password": "local-password",
    }

    assert _postgres_maxconn(base_config) == 5
    assert _postgres_maxconn({**base_config, "maxconn": 8}) == 8
    assert _postgres_pool_key(base_config) != _postgres_pool_key({**base_config, "maxconn": 8})


def test_ai_assist_uses_target_prompt_template_and_ready_flag(tmp_path: Path, monkeypatch) -> None:
    template_root = tmp_path / "ptemplate"
    assistant_root = template_root / "assistant"
    assistant_root.mkdir(parents=True)
    (assistant_root / "workitem.md").write_text("CUSTOM WORKITEM ASSISTANT PROMPT", encoding="utf-8")
    config = HWEConfig(
        prompt_template_root=template_root,
        ai_providers={"local": {"type": "openai_compatible", "base_url": "http://127.0.0.1:1234/v1", "model": "local-model"}},
    )
    captured: dict[str, object] = {}

    def fake_chat(_provider, messages):
        captured["messages"] = messages
        return '{"message":"Ready to apply.","ready":true,"draft":{"title":"Search notes"}}'

    monkeypatch.setattr(ai, "_chat_completion", fake_chat)

    response = create_ai_assist_response(
        config,
        provider_name="local",
        target="workitem",
        messages=[{"role": "user", "content": "Add search"}],
        draft={},
    )

    assert response["ready"] is True
    assert response["draft"] == {"title": "Search notes"}
    assert captured["messages"][0]["content"] == "CUSTOM WORKITEM ASSISTANT PROMPT"


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


def test_static_worker_tolerates_profile_switch_failure_by_default(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("Do the work", encoding="utf-8")
    context_path = tmp_path / "context.md"
    context_path.write_text("Context", encoding="utf-8")
    fake_hermes = tmp_path / "fake_hermes.py"
    fake_hermes.write_text("import sys\nprint('invoked')\nsys.exit(0)\n", encoding="utf-8")
    workflow_path = tmp_path / "workflow.yaml"
    workflow = {
        "workflow": {"id": "test-flow", "workspace": str(workspace)},
        "profiles": {
            "coder": {
                "switch_command": "python3 -c \"import sys; sys.exit(7)\"",
                "hermes_command": f"python3 {fake_hermes}",
            }
        },
        "steps": [{"id": "agent", "kind": "agent", "profile": "coder", "prompt": str(prompt_path)}],
    }
    workflow_path.write_text(yaml.safe_dump(workflow), encoding="utf-8")
    spec = load_workflow(workflow_path)
    adapter = WorkerAdapter(spec)

    result = adapter.run_agent_step(spec.steps[0], "run_static_switch", context_path)

    assert result.status == "succeeded"
    assert "invoked" in result.stdout_path.read_text(encoding="utf-8")
    assert "WARNING: Model switch command failed with exit code 7" in result.stderr_path.read_text(encoding="utf-8")


def test_static_worker_runs_switch_commands_independently(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("Do the work", encoding="utf-8")
    context_path = tmp_path / "context.md"
    context_path.write_text("Context", encoding="utf-8")
    fake_hermes = tmp_path / "fake_hermes.py"
    fake_hermes.write_text("import sys\nprint('invoked')\nsys.exit(0)\n", encoding="utf-8")
    switch_marker = workspace / "switch_marker.txt"
    workflow_path = tmp_path / "workflow.yaml"
    workflow = {
        "workflow": {"id": "test-flow", "workspace": str(workspace)},
        "profiles": {
            "coder": {
                "switch_commands": [
                    "python3 -c \"import sys; sys.stderr.write('not loaded\\n'); sys.exit(7)\"",
                    {
                        "command": f"python3 -c \"from pathlib import Path; Path('{switch_marker}').write_text('loaded', encoding='utf-8')\""
                    },
                ],
                "hermes_command": f"python3 {fake_hermes}",
            }
        },
        "steps": [{"id": "agent", "kind": "agent", "profile": "coder", "prompt": str(prompt_path)}],
    }
    workflow_path.write_text(yaml.safe_dump(workflow), encoding="utf-8")
    spec = load_workflow(workflow_path)
    adapter = WorkerAdapter(spec)

    result = adapter.run_agent_step(spec.steps[0], "run_static_switch_commands", context_path)

    assert result.status == "succeeded"
    assert switch_marker.read_text(encoding="utf-8") == "loaded"
    assert "invoked" in result.stdout_path.read_text(encoding="utf-8")
    stderr_text = result.stderr_path.read_text(encoding="utf-8")
    assert "not loaded" in stderr_text
    assert "WARNING: Model switch command failed with exit code 7" in stderr_text


def test_static_worker_closes_agent_stdin_by_default(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("Do the work", encoding="utf-8")
    context_path = tmp_path / "context.md"
    context_path.write_text("Context", encoding="utf-8")
    fake_hermes = tmp_path / "fake_hermes.py"
    fake_hermes.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "Path('stdin_text.txt').write_text(sys.stdin.read(), encoding='utf-8')\n"
        "print('done')\n",
        encoding="utf-8",
    )
    workflow_path = tmp_path / "workflow.yaml"
    workflow = {
        "workflow": {"id": "test-flow", "workspace": str(workspace)},
        "profiles": {"coder": {"hermes_command": f"python3 {fake_hermes}"}},
        "steps": [{"id": "agent", "kind": "agent", "profile": "coder", "prompt": str(prompt_path), "timeout_seconds": 5}],
    }
    workflow_path.write_text(yaml.safe_dump(workflow), encoding="utf-8")
    spec = load_workflow(workflow_path)
    adapter = WorkerAdapter(spec)

    result = adapter.run_agent_step(spec.steps[0], "run_static_closed_stdin", context_path)

    assert result.status == "succeeded"
    assert "done" in result.stdout_path.read_text(encoding="utf-8")
    assert (workspace / "stdin_text.txt").read_text(encoding="utf-8") == ""


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