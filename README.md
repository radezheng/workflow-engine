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
- Invoke Hermes with explicit profiles such as `hermes chat -p coder -Q --source workflow-engine -q <prompt>`.
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

Validate local repo/config/profile wiring with doctor before mutating workflow state on a new machine or after changing local config:

```bash
hwe doctor
hwe doctor --config /path/to/hwe.config.yaml --repo /path/to/workflow-engine
hwe doctor --fix
```

Doctor reports `OK`, `WARN`, and `FAIL` findings for repo discovery, CLI availability, config loading, workspace and template paths, project database reachability, profiles, healthchecks, and AI provider endpoints. `--fix` is intentionally limited to safe local directory creation; do not use it as permission to change credentials, ports, containers, schemas, profile commands, or model switch commands.

When a workflow omits `workflow.workspace`, HWE uses `default_workspace_root` from this config:

```yaml
default_workspace_root: ~/workspaces/hermes
prompt_template_root: ./ptemplate
workflow_template_root: ./workflow_templates
```

`prompt_template_root` is an HWE-side template library path, not a target project path. Relative values are resolved from the directory containing `hwe.config.yaml`; the default is `./ptemplate`.

`workflow_template_root` is an optional library for workflow template YAML files. HWE also ships built-in templates inside the package. Template files integrate workflow resources and flow rules: profiles, prompt template refs, planning/materialization task specs, parameters, and child workflow references such as QA or publish flows. Relative values are resolved from the config file directory; project-specific overrides can live under `<project>/.engine/workflow-templates/`.

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
    hermes_profile: coder
    hermes_command: hermes
    switch_commands:
      - lms unload reviewer-model
      - lms load coder-model --identifier coder-model --yes
    healthcheck:
      url: http://127.0.0.1:1234/v1/chat/completions
      model: coder-model
      retries: 5
      retry_delay_seconds: 2
      timeout_seconds: 30
```

`hwe worker` consumes queued run requests and runs `switch_commands` and `healthcheck` before invoking an agent task. Keep machine-specific model switching here, not in skills or generated project files.
    Healthcheck retries are meant to absorb slow model switching and server warmup. HWE logs each healthcheck attempt to the task run `stderr.log`; tune `retries`, `retry_delay_seconds`, and `timeout_seconds` for local model load time.
Use `switch_commands` for multi-step model changes such as unload/load; HWE runs each command independently, logs non-zero exits as warnings by default, and continues to the next switch step. The legacy `switch_command` string still works for single commands. Set `switch_command_required: true` on a profile, or `required: true` on a `switch_commands` mapping entry, when a failed switch must block the agent run.
Hermes hook prompts and dangerous-command approval prompts are handled by Hermes, not by HWE human actions. For trusted local profiles, set `hooks_auto_accept: true` in the Hermes profile config or configure `hermes_args: [--accept-hooks]` so hook prompts do not block headless runs. `--accept-hooks` does not approve dangerous shell commands; only `--yolo` bypasses those prompts, and HWE should not use it for routine runs. Agent prompts should steer workers toward non-interactive verification commands, especially avoiding pipe-to-interpreter patterns such as `curl | python`.

If a trusted profile needs a narrower dangerous-command exception, configure Hermes `command_allowlist` in the actual profile home used by HWE. Discover that home from the active Hermes installation, for example with `hermes profile show <profile>`, profile alias configuration, or the `HERMES_HOME` used when invoking the profile. Adding the allowlist only to the default Hermes config may not affect isolated profiles.
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
    # Use a real Hermes executable here; HWE passes hermes_profile as `-p coder`.
    hermes_command: hermes
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
hwe worker [project] [--once] [--max-requests N] [--profile PROFILE]
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

Human input is represented by `human_actions`, not by fake `kind=human-action` tasks. Workers that need operator input should create a real pending human action:

```bash
hwe human-action create my-project "Confirm credit-cycle indicators" \
  --project-id my-project \
  --workitem-id "$WORKITEM_ID" \
  --workflow-id "$WORKFLOW_ID" \
  --body "Confirm the indicator set before source research." \
  --question "Which indicators should be in scope?" \
  --option "Credit/GDP, policy rates, private-sector debt" \
  --requested-by designer
```

A pending human action attached to a workitem or its current workflow keeps the workitem in `waiting_for_human`, even when every task row is otherwise terminal. Answering or approving a task-linked human action moves that waiting task back to `ready`, so the next queued run request can rerun the task with the recorded response in context. Standalone human actions are for planning/materialization decisions that are not owned by one waiting task; after resolving one, the worker that requested it must create or run the continuation task that consumes the answer.

Archiving is a soft project-level state change. It keeps the project folder and workflow history intact, records project events, and hides the project from the default API/UI project list until it is restored or listed with archived projects included.

Run execution is split into a durable control plane and a long-running worker. UI, API, and the default CLI path enqueue rows in `run_requests`; `hwe worker` claims those requests and runs `ProjectRuntime` against the ready task queue. This keeps API requests short-lived and makes execution observable even when the UI disconnects.

```bash
hwe serve --host 127.0.0.1 --port 8711
hwe worker
hwe run-workitem my-project "$WORKITEM_ID" --max-tasks 1
```

`hwe run-workitem` defaults to POSTing to the local API (`HWE_API_URL` or `http://127.0.0.1:8711`) and returns the queued run request. Use `--local` only for recovery or tests when the API is unavailable; it bypasses HTTP but still enqueues a `run_requests` row for a worker to consume.

For `kind=command` tasks, `--prompt-text` is treated as the shell command and runs from the project root. For `kind=http_check` tasks, `--prompt-text` is either a URL or a JSON smoke-test spec that HWE runs with retries. For agent tasks, HWE combines the role prompt template, task prompt, HWE control context, work item context, declared skills, outputs, and gates into `.engine/runs/<run-id>/prompt.md`, then invokes the task profile through Hermes. The control context includes the HWE repo, explicit config path, CLI command, project/workitem/workflow/task ids, and configured profile list so workers do not invent unavailable profiles or guess local commands. `task_run_started` events include the `run_id`, and started runs register stdout/stderr/prompt paths as soon as those files are created so the UI/API can read logs while a task is still running. Run logs include an HWE header with kind, cwd, profile when applicable, the executed command, child process console output, and exit code; agent commands log the `prompt.md` path instead of inlining the full prompt. When Hermes emits a `session_id`, HWE stores it in the run result and `/api/projects/<project>/runs/<run-id>/timeline` reads the matching local Hermes session JSONL when present, exposing visible user/assistant/tool events for debugging. `--dry-run` writes prompts and logs without invoking Hermes or running shell commands.

When a planning/design task succeeds, the next step is decided by the selected workflow template, not by hardcoded task names. The built-in `software-project-dev` template defines the default PM controller profile, designer planning task, reviewer gate, materialization sources, breakdown task, profile parameters, prompt template refs, task post-execution controller hook, and child workflow references for QA and publish flows. HWE does not parse natural-language plan output itself, and the default coordinator should not manually transcribe designer stdout into implementation tasks during normal flow. Instead, the UI/API create template-defined review tasks after planning; only a succeeded review source exposes the materialization action. The materialization task receives the reviewed plan/design `stdout.log` path plus the review evidence path and creates the task graph through HWE commands. HWE-generated task prompt wrappers are written in Chinese; user-provided requirements and constraints keep their original language.

Example workflow template fragment:

```yaml
id: software-project-dev
parameters:
  pm_profile: {default: '${designer_profile}'}
  designer_profile: {default: designer}
  reviewer_profile: {default: reviewer}
  recovery_prompt_template: {default: pm/recovery-plan}
  task_breakdown_prompt_template: {default: designer/task-breakdown}
profiles:
  pm: ${pm_profile}
planning_task:
  stage: workitem-plan
  profile: ${designer_profile}
  prompt_template_ref: ${plan_prompt_template}
review_tasks:
  - stage: workitem-plan-review
    profile: ${reviewer_profile}
    prompt_template_ref: reviewer/planning-review
materialize:
  sources:
    - stage: workitem-plan-review
      prompt_template_ref: reviewer/planning-review
  task:
    stage: task-breakdown
    profile: ${designer_profile}
    prompt_template_ref: ${task_breakdown_prompt_template}
child_workflows:
  - id: qa
    template: qa-review
task_completion:
  sources:
    - statuses: [succeeded, failed, cancelled, skipped, superseded, waiting_for_info, waiting_for_approval]
  post_execution:
    profile: ${pm_profile}
    prompt_template_ref: ${recovery_prompt_template}
```

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

When a task finishes in any configured completion status, HWE automatically queues a workflow-template-defined `post_execution` run request when the selected template provides `task_completion`. This is not a PM task record; it is the completed task's controller hook. The built-in templates default `pm_profile` to `designer`, so existing installs do not need a separate `pm` profile unless they want one. PM post-execution receives the source task id/status, run id, stdout/stderr paths, result JSON, project/workitem/workflow ids, project root, and HWE CLI/control context. It must decide whether to continue, wait, retry, create a replacement verification task, create a focused fix task, or send the work back through design. If PM succeeds after a successful/skipped/superseded source task and the workflow already has ready tasks but no queued workitem/task request, the worker enqueues a one-step workitem continuation. PM post-execution prompts also require workflow-template improvement suggestions when the outcome reveals a repeatable process gap.

Pending human actions attached to a workitem or its current workflow block task claiming for that workitem until the action is resolved, even if tasks are otherwise `ready`.

Treat failed `command` and `http_check` tasks as deterministic workflow gate failures. Inspect run logs and the task definition before retrying. If the verification command is wrong for the project layout, create a replacement verification task and mark the obsolete gate `superseded` only after replacement evidence succeeds. If the command is correct and exposes a product defect, create a focused fix task and rerun or replace the gate after the fix. Durable recovery paths belong in workflow templates rather than one-off operator prose.

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

If a command or runner is cancelled and leaves a task `running`, first inspect recent events and any active task run logs. A `running` task may still be actively switching models, waiting on healthcheck, running Hermes, or executing a command. Release only after you have evidence that the runner was interrupted, crashed, or abandoned. Then release it back to `ready`:

```bash
hwe task release my-project "$TASK_ID" --reason abandoned-run
```

Releasing a running task also marks any still-started task runs for that task as `cancelled` with the release reason, so run history reflects the abandoned execution instead of leaving a stale `started` run. If HWE catches an interactive interrupt while running a task, it also records the active run and task as `cancelled`; hard process kills can still require manual release.

After release, a pending or ready task can be reassigned to another profile without deleting prior run history:

```bash
hwe task reassign my-project "$TASK_ID" --profile designer --reason switch-profile
```

Do not run endless background retry loops for a repeatedly running or timing-out agent task. Inspect `.engine/runs/<run-id>/prompt.md`, `stdout.log`, and `stderr.log`, then narrow the task, adjust timeout/model readiness, retry a transient failure, or create a human action if the task needs clarification.

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

Standalone human actions also block the associated workitem as `waiting_for_human`, but resolving them does not by itself create work. If the answer changes scope or unlocks the next phase, create or run a concrete follow-up task after recording the answer.

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

Workflow templates are YAML files, not database records. Built-ins ship with HWE under `src/hermes_workflow_engine/workflow_templates/`; config-level overrides can be placed under `workflow_template_root`, and project-local overrides under `.engine/workflow-templates/`. The API exposes resolved templates at `GET /api/projects/{project_ref}/workflow-templates`. Plan requests can pass `workflow_template_id` and `parameters`, and materialization requests use the same template to validate source tasks and render the next task input. This keeps workflow behavior configurable without parsing plan prose in Python or TypeScript.

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

The console can create projects under `default_workspace_root`, archive or restore projects, create workitems, use configured AI providers to draft project/workitem/human-action/prompt-template inputs through multi-turn chat, and show project discovery, workitem selection, task queue status, task runs/logs, Hermes session timelines, human actions, and recent events. Archived projects are hidden by default and can be shown with the Show archived toggle; they remain readable, while workflow mutation controls are disabled until restore. Workitems are planned from a selected workflow template. Succeeded tasks expose Break down plan only when the API reports a workflow-template action for that task. The console also includes Prompt Templates and Settings surfaces: Prompt Templates lists public library files, project overrides, save-to-project actions, and push-public actions, while Settings shows the active HWE config path, workspace root, prompt template root, profiles, and AI provider names. Planned surfaces such as graph view, live logs, and daemon controls are visible as disabled menu entries so they stay on the roadmap.

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
