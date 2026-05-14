# Hermes Workflow Engine

This is a local MVP implementation of the workflow engine described in [workflow_engine_design.md](workflow_engine_design.md). It drives Hermes profiles as bounded subprocess workers while keeping workflow state, context bundles, logs, artifacts, gate results, and events under each target project's `.engine/` directory.

## What Works Now

- Parse a `workflow.yaml` spec.
- Support one shared workspace root with per-project folders.
- Store workflow, step, run, event, context, artifact, and gate state in SQLite.
- Run `command` steps and Hermes `agent` steps serially.
- Respect `needs` dependencies for serial scheduling.
- Compile deterministic context bundles before worker launch.
- Run profile preflight: optional model switch command and optional LM Studio-style healthcheck.
- Invoke Hermes through profile aliases such as `coder chat -Q --source workflow-engine -q <prompt>`.
- Capture stdout, stderr, final prompt, result JSON, artifact snapshots, and git diff.
- Run initial deterministic validators.
- Support `--dry-run` for exercising workflow scheduling without launching Hermes.

## Install For Local Development

Clone the public repository:

```bash
git clone https://github.com/radezheng/workflow-engine.git
cd workflow-engine
```

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

You can also run directly without installing:

```bash
PYTHONPATH=src python3 -m hermes_workflow_engine --help
```

For Hermes `default` profile bootstrapping, including owner-confirmed install/update parameters, copying the bundled HWE skill, and running config/environment self-checks, see [docs/hermes-bootstrap.md](docs/hermes-bootstrap.md).

For a full local config shape, see [docs/hwe.config.example.yaml](docs/hwe.config.example.yaml).

To update an existing checkout:

```bash
git status --short
git pull --ff-only
source .venv/bin/activate
pip install -e .
```

If local changes are present, commit or stash them before updating.

## Try The Example

The example writes a small file with a command step, then dry-runs a coder profile step.

```bash
PYTHONPATH=src python3 -m hermes_workflow_engine run examples/workflow.yaml --dry-run
PYTHONPATH=src python3 -m hermes_workflow_engine status examples/workflow.yaml
PYTHONPATH=src python3 -m hermes_workflow_engine events examples/workflow.yaml
```

Runtime files are written to the example project's `.engine/` directory.

## Workspace And Project Layout

For multiple projects, use `workflow.workspace` as the shared workspace root and `workflow.project` as the project folder under it:

```yaml
workflow:
  id: my-project-flow
  workspace: /path/to/hermes-workspace
  project: my-project
```

All commands, Hermes profile invocations, output paths, validators, artifacts, and state then use `/path/to/hermes-workspace/my-project` as the project workspace. That project gets its own `.engine/` directory, so progress is tracked independently per project. If `workflow.project` is omitted, the old single-project behavior is preserved and `workflow.workspace` itself is treated as the project workspace.

## HWE Local Config

Machine-specific defaults belong in HWE config, not in skills or workflow templates. By default, HWE looks for `hwe.config.yaml` from the current directory upward. If none exists, `hwe config init` creates `hwe.config.yaml` in the current directory. Set `HWE_CONFIG` to use an explicit file.

Create or inspect the local config with:

```bash
hwe config init --default-workspace-root ~/workspaces/hermes --prompt-template-root ./ptemplate
hwe config show
hwe config path
```

When a workflow omits `workflow.workspace`, HWE uses `default_workspace_root` from this config:

```yaml
default_workspace_root: ~/workspaces/hermes
prompt_template_root: ./ptemplate
```

`prompt_template_root` is an HWE-side template library path, not a target project path. Relative values are resolved from the directory containing `hwe.config.yaml`; the default is `./ptemplate`.

Project workflow state uses SQLite by default, with one database at `<project>/.engine/engine.db`. To use a central local PostgreSQL database instead, configure `project_database` in `hwe.config.yaml`:

```yaml
project_database:
  backend: postgres
  host: 127.0.0.1
  port: 5432
  database: hindsight_db
  user: hindsight_user
  schema: hwe
  gssencmode: disable
  maxconn: 5
  password: local-password
```

`hwe.config.yaml` is local and gitignored, so machine-specific database passwords may live there. For shared examples or hosted services, prefer `password_env` or `password_command` instead of a literal password. HWE does not create, stop, or mutate the Postgres container; it only creates and uses the configured schema and tables.
Postgres storage uses a process-local connection pool; tune `maxconn` for API concurrency and local database capacity.
For local Docker PostgreSQL on macOS, keep `gssencmode: disable` unless you explicitly use GSS/Kerberos; otherwise libpq can spend about 30 seconds per connection attempting GSSAPI negotiation.

Project workflow agent tasks can also use HWE-local profile preflight settings:

```yaml
profiles:
  coder:
    hermes_command: coder
    switch_commands:
      - lms unload reviewer-model
      - lms load coder-model --identifier coder-model --yes
    healthcheck:
      url: http://127.0.0.1:1234/v1/chat/completions
      model: coder-model
      retries: 5
      retry_delay_seconds: 2
```

`run-workitem` runs `switch_commands` and `healthcheck` before invoking an agent task. Keep machine-specific model switching here, not in skills or generated project files.
Use `switch_commands` for multi-step model changes such as unload/load; HWE runs each command independently, logs non-zero exits as warnings by default, and continues to the next switch step. The legacy `switch_command` string still works for single commands. Set `switch_command_required: true` on a profile, or `required: true` on a `switch_commands` mapping entry, when a failed switch must block the agent run.
Hermes hook prompts and dangerous-command approval prompts are handled by Hermes, not by HWE human actions. For trusted local profiles, set `hooks_auto_accept: true` in the Hermes profile config or configure `hermes_args: [--accept-hooks]` so hook prompts do not block headless runs. Do not use `--yolo` for routine HWE runs; dangerous-command prompts should fail or receive EOF instead of being broadly bypassed.
If Hermes enters its clarify flow during a headless run and only emits a `clarify timed out` marker before the task timeout, HWE treats that as missing operator input instead of an ordinary failure. It writes `.engine/runs/<run-id>/clarification.md`, marks the task `waiting_for_info`, and creates a human action with links to `prompt.md`, `stdout.log`, `stderr.log`, and the clarification note. The exact question can only appear there if Hermes emitted it to its logs.

The local UI can use AI-assisted form drafting for project, workitem, and human-action inputs. Configure one or more OpenAI-compatible providers under `ai_providers`:

```yaml
ai_providers:
  local-lms:
    type: openai_compatible
    base_url: http://127.0.0.1:1234/v1
    model: local-model
  openai:
    type: openai_compatible
    base_url: https://api.openai.com/v1
    model: gpt-4.1-mini
    api_key_env: OPENAI_API_KEY
```

The UI lists configured providers and sends multi-turn assistant requests through HWE's API. When drafting a new workitem from a selected project, HWE includes a compact project context with existing workitems, current workflow IDs, task status counts, and recent task titles. Use `api_key_env` for hosted providers; do not store API keys directly in tracked files.

During Hermes bootstrap, use the current Hermes profile's OpenAI-compatible provider as the first HWE `ai_providers` entry when available. If the current profile has only one provider, configure one HWE provider; `ai_providers` are for UI drafting and do not need one entry per worker profile.

Then a workflow can specify only the project name:

```yaml
workflow:
  id: my-project-flow
  project: my-project
```

## Running A Real Hermes Profile Step

Set the workflow workspace and optional project folder to the project you want Hermes to edit, then define an `agent` step:

```yaml
steps:
  - id: implement_slice
    title: Implement focused slice
    kind: agent
    profile: coder
    locks: [repo]
    prompt: prompts/implement_slice.md
    context:
      include:
        - artifacts.paths:
            - docs/requirements.md
            - docs/design.md
    outputs:
      - src/feature.py
    review:
      mode: inline
      reviewer: reviewer
      gates:
        - python_syntax_ok
        - no_hardcoded_credentials
```

Profiles map workflow names to Hermes profiles and optional model preflight:

```yaml
profiles:
  coder:
    hermes_profile: coder
    # Optional. Defaults to the profile alias when it exists, then HERMES_BIN/hermes.
    hermes_command: coder
    hermes_args: [--accept-hooks]
    # Optional. Prefer separate steps for local unload/load flows.
    switch_commands:
      - ./scripts/unload-reviewer-profile.sh
      - ./scripts/use-coder-profile.sh
    healthcheck:
      url: http://localhost:1234/v1/chat/completions
      model: coder-model
```

## CLI

```bash
hwe validate workflow.yaml
hwe run workflow.yaml [--dry-run] [--max-steps N]
hwe status workflow.yaml
hwe events workflow.yaml [--limit N]
hwe serve [--host 127.0.0.1] [--port 8711] [--reload]
```

## Project/WorkItem/Task Queue

Project workflow mode stores project, work item, workflow, task queue, task run, human action, and event records. By default this state lives in each project's `.engine/engine.db`; when `project_database.backend: postgres` is configured, those records live in the configured PostgreSQL schema while project files, prompt-template overrides, and run logs remain under the project `.engine/` directory.

```bash
hwe project init my-project --id my-project
hwe project archive my-project --id my-project
hwe project restore my-project --id my-project

WORKITEM_ID=$(hwe workitem create my-project "Add notes" \
  --requirements "Support Markdown notes" \
  --acceptance "Create, edit, delete, and view notes" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

WORKFLOW_ID=$(hwe workflow create my-project "$WORKITEM_ID" \
  --planner-profile designer \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

hwe task create my-project "$WORKFLOW_ID" "Design notes" --kind design --profile designer
hwe task list my-project "$WORKFLOW_ID"
hwe task claim my-project "$WORKFLOW_ID" --worker-id local-designer --profile designer
```

Archiving is a soft project-level state change. It keeps the project folder and workflow history intact, records project events, and hides the project from the default API/UI project list until it is restored or listed with archived projects included.

To run the ready task queue directly from the CLI, use `run-workitem`. This is the push-style runner that API and UI layers can build on later:

```bash
hwe run-workitem my-project "$WORKITEM_ID" --dry-run --max-tasks 1
```

For `kind=command` tasks, `--prompt-text` is treated as the shell command and runs from the project root. For `kind=http_check` tasks, `--prompt-text` is either a URL or a JSON smoke-test spec that HWE runs with retries. For agent tasks, HWE combines the role prompt template, task prompt, work item context, declared skills, outputs, and gates into `.engine/runs/<run-id>/prompt.md`, then invokes the task profile through Hermes. `task_run_started` events include the `run_id`, and started runs register stdout/stderr/prompt paths as soon as those files are created so the UI/API can read logs while a task is still running. `--dry-run` writes prompts and logs without invoking Hermes or running shell commands.

When a planning task succeeds, the next step is a follow-up designer task that breaks the plan into executable HWE tasks. HWE does not parse natural-language plan output itself, and the default coordinator should not manually transcribe designer stdout into implementation tasks during normal flow. Instead, the UI opens a dialog with the selected prompt template and editable input, including the successful plan stdout path, then the API creates one designer breakdown task that reads the plan file and creates the task graph through HWE commands. CLI/default-profile workflows should follow the same staged pattern: use `designer/workitem-plan` for initial planning, `designer/technical-design` for existing projects or architecture-sensitive work, then `designer/task-breakdown` with the plan/design `stdout.log` path. The breakdown task should verify available profiles and prompt templates, and may create project-local template overrides under `.engine/prompt-templates/<role>/<name>.md` when public templates are not suitable. HWE-generated task prompt wrappers are written in Chinese; user-provided requirements and constraints keep their original language.

Example HTTP smoke task:

```bash
hwe task create my-project "$WORKFLOW_ID" "Smoke: backend and UI" \
  --kind http_check \
  --profile command \
  --prompt-text '{
    "requests": [
      {"url": "http://127.0.0.1:8000/health", "expect_status": 200, "expect_json": {"status": "healthy"}},
      {"url": "http://127.0.0.1:3000", "expect_status": 200, "expect_contains": "Notes"}
    ]
  }'
```

Each HTTP request supports `method`, `headers`, `json`, `body`, `expect_status`, `expect_json`, `expect_contains`, `retries`, `retry_delay_seconds`, and `timeout_seconds`. This is intended for final runtime checks such as backend health, API create/list/search, and frontend page compilation after separate command tasks have started the app or after the user has started project servers.

When a task is completed with `hwe task complete <project> <task-id>`, dependent tasks whose prerequisites succeeded become `ready` automatically. `skipped` and `superseded` are also terminal dependency-satisfying statuses for obsolete or duplicate work. Use them deliberately, with a result reason, when a replacement task has already delivered the intended output:

```bash
hwe task complete my-project "$OLD_TASK_ID" \
  --status superseded \
  --result-json '{"reason":"replacement backend init task succeeded"}'
```

Transient failures can be returned to `ready` without losing run history:

```bash
hwe task retry my-project "$TASK_ID" --reason transient-healthcheck
```

If a command or runner is cancelled and leaves a task claimed, first inspect recent events and any active task run logs. A `claimed` task may still be actively running; release only after you have evidence that the runner was interrupted, crashed, or abandoned. Then release the claim back to `ready`:

```bash
hwe task release my-project "$TASK_ID" --reason abandoned-run
```

Do not run endless background retry loops for a repeatedly claimed or timing-out agent task. Inspect `.engine/runs/<run-id>/prompt.md`, `stdout.log`, and `stderr.log`, then narrow the task, adjust timeout/model readiness, retry a transient failure, or create a human action if the task needs clarification.

Tasks can also pause for human input or approval. Completing a task with `waiting_for_info` or `waiting_for_approval` creates a pending human action and releases the worker claim:

```bash
hwe task complete my-project "$TASK_ID" \
  --status waiting_for_info \
  --title "Choose persistence target" \
  --body "Should notes use PostgreSQL or browser storage?" \
  --question "Where should notes be stored?" \
  --option PostgreSQL \
  --option "Local browser only"

hwe human-action list my-project --status pending
hwe answer my-project "$HUMAN_ACTION_ID" --text "Use PostgreSQL"
```

For approval requests, use `hwe approve <project> <human-action-id>` or `hwe reject <project> <human-action-id> --reason "..."`. Answering or approving an action moves the waiting task back to `ready`; rejecting it marks the task `failed` so dependent tasks stay blocked.

Agent tasks can also enter `waiting_for_info` automatically when Hermes reports a clarify timeout and then the headless process times out. In that case, inspect `.engine/runs/<run-id>/clarification.md` along with `prompt.md`, `stdout.log`, and `stderr.log`, answer the generated human action with the missing clarification or retry direction, then rerun the workitem.

Role prompt templates are Markdown files, not database records. Public HWE templates live under `<prompt_template_root>/<role>/<name>.md`; project-specific overrides live under `<project>/.engine/prompt-templates/<role>/<name>.md`. Tasks reference a template by `role/name`, and HWE loads the project file first, then falls back to the public library:

```bash
hwe task create my-project "$WORKFLOW_ID" "Review implementation" \
  --kind review \
  --profile reviewer \
  --prompt-template-ref reviewer/implementation-review \
  --skill hermes-project-workflow
```

The API/UI Prompt Templates surface lists both public and project files. Saving writes a project-local file; pushing public writes the shared HWE template library.

## API And UI Console

HWE includes a local FastAPI service and Vite React console for project workflow mode. Start the API from the repository root:

```bash
hwe serve --host 127.0.0.1 --port 8711
```

Start the UI in another terminal:

```bash
cd ui
npm install
npm run dev
```

The UI defaults to `http://127.0.0.1:8711` for the API and opens at `http://127.0.0.1:5173`. Set `VITE_HWE_API_BASE` before `npm run dev` if the API runs elsewhere.

The console can create projects under `default_workspace_root`, archive or restore projects, create workitems, use configured AI providers to draft project/workitem/human-action/prompt-template inputs through multi-turn chat, and show project discovery, workitem selection, task queue status, task runs/logs, human actions, and recent events. Archived projects are hidden by default and can be shown with the Show archived toggle; they remain readable, while workflow mutation controls are disabled until restore. Succeeded planning tasks expose a Break down plan action that opens a prompt/input dialog before creating the designer breakdown task. The console also includes Prompt Templates and Settings surfaces: Prompt Templates lists public library files, project overrides, save-to-project actions, and push-public actions, while Settings shows the active HWE config path, workspace root, prompt template root, profiles, and AI provider names. Planned surfaces such as graph view, live logs, and daemon controls are visible as disabled menu entries so they stay on the roadmap.

## Current Validator Names

- `git_initialized`
- `planning_docs_complete`
- `external_services_declared`
- `no_hardcoded_credentials`
- `no_external_service_mutation`
- `no_placeholder_ingestion`
- `source_evidence_required`
- `python_syntax_ok`
- `node_build_ok`
- `review_result_parseable`
- `no_untracked_debug_artifacts`

Unknown gate names are recorded as `skipped` so specs can be forward-compatible while the plugin surface grows.
