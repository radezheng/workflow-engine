---
name: hwe
description: "Use when: driving work through Hermes Workflow Engine (HWE), running hwe doctor config/environment checks, creating or running project/workitem/workflow/task queues, planning HWE tasks, using hwe run-workitem, handling human actions, prompt templates, task retry/release/superseded, runtime smoke checks, local Hermes profile orchestration, or external PostgreSQL/Docker safety."
argument-hint: "[doctor|project/workitem/workflow/task operation]"
version: 0.1.0
metadata:
  hermes:
    tags: [hwe, workflow-engine, project-workflow, task-queue, qa, runtime-smoke, postgres, safety]
    related_skills: []
---

# HWE: Hermes Workflow Engine

Use this skill when the user wants Hermes profiles to plan, implement, review, and verify work through the local Hermes Workflow Engine (`hwe`) rather than through ad hoc chat or the old Kanban/project-template workflow.

HWE owns workflow state and scheduling. Hermes profiles are workers.

Public HWE repository: `https://github.com/radezheng/workflow-engine`

This `SKILL.md` is the operational entrypoint. Keep critical safety and workflow rules here; move bulky examples or rare maintenance guidance into supporting files such as [skill-maintenance](./references/skill-maintenance.md).

Do not assume machine-specific paths, ports, workspace roots, model names, or database services. Discover them from `HWE_REPO`, `HWE_CONFIG`, the active `hwe.config.yaml`, command-line arguments, or the current repository.

## Install Or Update HWE

When the user asks to install, update, repair, or bootstrap HWE, use the public repository, then run doctor before mutating workflow state. Install into an operator-approved directory:

```bash
export HWE_REPO=${HWE_REPO:-$HOME/workflow-engine}
git clone https://github.com/radezheng/workflow-engine.git "$HWE_REPO"
cd "$HWE_REPO"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
export HWE=$PWD/.venv/bin/hwe
export HWE_PYTHON=$PWD/.venv/bin/python
export HWE_CONFIG=${HWE_CONFIG:-$PWD/hwe.config.yaml}
```

Update an existing checkout only when it has no unresolved local changes; if `git status --short` shows local changes, ask whether to commit, stash, or keep them:

```bash
cd "$HWE_REPO"
git status --short
git pull --ff-only
. .venv/bin/activate
python -m pip install -e .
```

After install or update, sync the bundled skill into Hermes and run doctor:

```bash
mkdir -p "$HOME/.hermes/skills"
rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' \
  "$HWE_REPO/.agents/skills/hwe/" \
  "$HOME/.hermes/skills/hwe/"
"$HWE_PYTHON" "$HWE_REPO/.agents/skills/hwe/scripts/doctor.py" --repo "$HWE_REPO" --config "$HWE_CONFIG"
```

If HWE dispatches to multiple Hermes profiles, copy the full `hwe` skill directory into each target profile's configured skill directory and re-check discovery before running agent tasks.

## Operating Checkpoints

Before acting through HWE, run these checkpoints:

1. Resolve the HWE repo and config. If anything looks mismatched, run `/hwe doctor` before mutating workflow state.
2. Resolve the project through configured HWE state (`HWE_CONFIG`, API, or `ProjectStorage`), not by filesystem guesses.
3. Before creating agent tasks, verify profile ownership, prompt template refs, and target-profile skill availability.
4. Before running tasks, ensure requirements and approvals are clear; convert ambiguity into HWE human actions.
5. During execution, keep runners visible, stop auto-run on failure or human input, and do not start competing runners for the same workitem.
6. Before recovering a `claimed` task, inspect events, active runs, logs, and known runner processes; release only abandoned claims.

## Core Model

- **Project**: a real workspace folder. Each project owns its own `.engine/` directory for run logs and project prompt-template overrides. Workflow state uses project-local SQLite by default, or a configured PostgreSQL schema when `project_database.backend: postgres` is set in HWE config.
- **Workitem**: the user-facing unit of delivery, such as a feature, bugfix, or maintenance request.
- **Workflow**: the current execution strategy for one workitem.
- **Task**: the worker-facing unit of execution. Tasks are narrow, auditable, and dependency-aware.
- **Profiles**: the `designer` profile owns PM clarification, planning, and technical design. The `reviewer` profile owns implementation review, QA review, test evidence, and acceptance. The `coder` profile only writes focused implementation or fix slices.

- **Runner discipline**: Run HWE control commands in the foreground unless starting the known local API/UI services. Do not create unmonitored background `run-workitem` loops; background runners make claimed-task recovery ambiguous and can duplicate work.

## First Checks

Before creating or running project workflow tasks:

```bash
HWE_REPO=${HWE_REPO:-$(pwd)}
HWE_CONFIG=${HWE_CONFIG:-$HWE_REPO/hwe.config.yaml}
HWE=${HWE:-$HWE_REPO/.venv/bin/hwe}
HWE_PYTHON=${HWE_PYTHON:-$HWE_REPO/.venv/bin/python}
cd "$HWE_REPO"
export HWE_CONFIG
"$HWE" config show
"$HWE" project show <project> --id <project-id>
"$HWE" workitem list <project> --project-id <project-id>
```

For project discovery, do not infer "no HWE projects" by scanning folders for `.engine/` only. HWE workflow state may live in PostgreSQL, and HWE config discovery depends on the current working directory unless `HWE_CONFIG` is set. Use the repo-local config explicitly and query HWE state:

```bash
HWE_API_URL=${HWE_API_URL:-http://127.0.0.1:${HWE_API_PORT:-8711}}
curl -sS "$HWE_API_URL/api/projects?include_archived=true"
```

If the API is not running, use HWE's storage layer with the same config rather than filesystem guesses:

```bash
cd "$HWE_REPO"
HWE_CONFIG="$HWE_CONFIG" "$HWE_PYTHON" - <<'PY'
from hermes_workflow_engine.config import load_config
from hermes_workflow_engine.project_storage import ProjectStorage
config = load_config()
project_name = '<project>'
project_root = (config.default_workspace_root / project_name) if config.default_workspace_root else project_name
storage = ProjectStorage(project_root, config=config)
for project in storage.list_projects(include_archived=True):
  print(project['id'], project['status'], project['root_path'])
PY
```

Projects can be archived without deleting files or workflow history:

```bash
hwe project archive <project> --id <project-id>
hwe project restore <project> --id <project-id>
```

Archived projects keep their workflow history, are hidden from default project discovery, and should be treated as read-only operationally until restored.

If the project is referred to by name, resolve it through `default_workspace_root` from `hwe.config.yaml`. Target projects should normally live under that configured workspace root, not inside the workflow-engine repository.

Machine-specific details such as model names, model switch commands, local API URLs, AI provider settings, project database connection settings, and default workspace root belong in HWE's local `hwe.config.yaml`, environment variables, or operator-provided arguments, not in generated project code or this skill. Hosted AI provider secrets should be referenced through environment variables such as `api_key_env`, not stored in tracked files.

If `project_database.backend: postgres` is configured, use the configured database and schema for HWE project/workitem/workflow/task state while leaving project files and `.engine/runs/` logs in the project folder. Treat configured database services as external infrastructure: do not stop, recreate, rename, or reconfigure containers, credentials, ports, schemas, or volumes unless the user explicitly asks. Tune the process-local storage pool with `project_database.maxconn` when needed.

## HWE Doctor

When the user invokes `/hwe doctor`, asks why HWE projects disappeared, reports profile/template/config mismatch, or asks to validate a new environment, run the bundled doctor workflow before making workflow changes.

Doctor checks should inspect:

- HWE repo discovery and `HWE_CONFIG` resolution.
- Whether the `hwe` command or repo virtualenv command is executable.
- Whether `hwe.config.yaml` loads and validates.
- `default_workspace_root` and `prompt_template_root` existence.
- Project database backend, Postgres reachability/login when configured, and missing credential environment variables.
- Configured profiles, `hermes_command`, switch command executables, healthcheck URLs, and `success_exit_codes` shape.
- AI provider base URLs and secret environment variables.
- Prompt templates and target-profile skill availability before creating agent tasks.

Run the bundled script from this skill directory when available:

```bash
"${HWE_PYTHON:-python3}" scripts/doctor.py --repo "${HWE_REPO:-$PWD}" --config "${HWE_CONFIG:-${HWE_REPO:-$PWD}/hwe.config.yaml}"
```

Use `--fix` only for safe local fixes such as creating configured local directories:

```bash
"${HWE_PYTHON:-python3}" scripts/doctor.py --repo "${HWE_REPO:-$PWD}" --config "${HWE_CONFIG:-${HWE_REPO:-$PWD}/hwe.config.yaml}" --fix
```

Doctor may auto-fix reversible local mismatches. It must ask the user before changing credentials, ports, database/container lifecycle, schemas, profile commands, model switch commands, API/UI service lifecycle, or overwriting an existing profile-local skill. Report findings as `OK`, `WARN`, and `FAIL`, include the exact config path and repo path used, and list any changes made.

## API And UI Console

Use the UI for operator visibility when the user wants to inspect workitems, task queues, task runs/logs, human actions, and recent events:

```bash
cd "$HWE_REPO"
HWE_CONFIG="$HWE_CONFIG" "$HWE" serve --host "${HWE_API_HOST:-127.0.0.1}" --port "${HWE_API_PORT:-8711}"
npm --prefix ui install
npm --prefix ui run dev -- --host "${HWE_UI_HOST:-127.0.0.1}" --port "${HWE_UI_PORT:-5173}"
```

Always start `hwe serve` from the HWE repository root, or set `HWE_CONFIG` to the intended config path. HWE discovers its config from the current working directory and parents unless `HWE_CONFIG` is set. If Hermes starts the API from an unrelated directory or a generated project directory, HWE may load the wrong config and appear to have no existing projects. Run `/hwe doctor` when project discovery disagrees with expectations.

To stop the local console, stop only the HWE API/UI processes for the known ports:

```bash
api_pids=$(lsof -ti tcp:${HWE_API_PORT:-8711} 2>/dev/null || true); [[ -n "$api_pids" ]] && kill $api_pids
ui_pids=$(lsof -ti tcp:${HWE_UI_PORT:-5173} 2>/dev/null || true); [[ -n "$ui_pids" ]] && kill $ui_pids
```

After changing `hwe.config.yaml`, restart the HWE API so the server process reloads profile settings and `default_workspace_root`. The Vite UI usually does not need a restart unless frontend source files or dependencies changed.

The UI is a local operational console over project workflow state. It can archive/restore projects, hide archived projects by default, and show them through a Show archived toggle. Archived projects remain readable, but workflow mutation controls should stay disabled until restore. The UI can use configured `ai_providers` for multi-turn drafting of project, workitem, human-action, and prompt-template inputs; workitem drafting should include compact context from the selected project's existing workitems, workflows, and task status summaries. For succeeded planning tasks, plan breakdown should open a prompt/input dialog and then create one designer task that receives the plan stdout path; HWE should not parse natural-language plan output into tasks in Python/TypeScript. Keep it modular: `App.tsx` should orchestrate state, while menu items, lists, rows, detail panels, AI assist widgets, and shared widgets live under `ui/src/components/`.

## Creating A Project Workflow

For a new request, create or reuse a project, workitem, workflow, and initial planning task:

```bash
hwe project init <project> --id <project-id>

WORKITEM_ID=$(hwe workitem create <project> "<title>" \
  --project-id <project-id> \
  --requirements "<requirements>" \
  --constraints "<constraints>" \
  --acceptance "<acceptance criterion>" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

WORKFLOW_ID=$(hwe workflow create <project> "$WORKITEM_ID" \
  --project-id <project-id> \
  --planner-profile designer \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

hwe task create <project> "$WORKFLOW_ID" "Plan and dispatch" \
  --kind design \
  --profile designer \
  --skill hwe \
  --prompt-text "Plan the workitem, write requirements/design if needed, create focused implementation, review, and runtime smoke tasks."
```

Then run ready tasks with the push-style runner:

```bash
hwe run-workitem <project> "$WORKITEM_ID" --project-id <project-id> --max-tasks 1
```

Use `--max-tasks 1` while dogfooding or debugging so profile switching, logs, and task outcomes stay easy to inspect.

Auto-run is allowed only when the ready task queue is already clear and each task has explicit requirements, dependencies, and deterministic stop conditions. After task breakdown has produced a concrete queue, it is reasonable to try Run Next with Auto to advance the workflow. The CLI can run all currently ready tasks by omitting `--max-tasks`; the UI Auto toggle repeatedly runs one ready task at a time and stops when there are no ready tasks, a task fails, or a task waits for human input. Do not use auto-run to push through ambiguous requirements, missing approvals, destructive operations, external infrastructure changes, or broad implementation tasks that have not been reviewed. If uncertainty appears while auto-running, stop and ask the user or create a focused HWE human action before continuing.

## Software Project Development Flow

When the workitem is software project development and the remote user talks only to the `default` profile, use this flow instead of improvising step by step:

1. **Intake**: Resolve or create the project/workitem/workflow. Summarize the requested behavior, constraints, external services, ports, data retention, and acceptance criteria. If any of these are unclear, ask the user or create `waiting_for_info` before implementation.
2. **Design**: Create or run one planning/design task that produces a short technical plan: target files, architecture choices, risks, test strategy, and task breakdown. Use `designer` only if HWE will actually route that profile and its required skills are verified; otherwise use `default` and record the same outputs.
3. **Task Queue**: Materialize a concrete queue from the plan. Prefer several narrow `impl`/`fix` tasks, deterministic `command` checks, `http_check` smoke tests for runnable apps, and final review/acceptance tasks. Every implementation task should name intended files, constraints, dependencies, and verification.
4. **Implementation Slices**: Run one narrow implementation task at a time. Do not combine broad product design, coding, review, and smoke testing in one prompt. After each slice, run its nearest deterministic check or create the next fix task.
5. **Integration And Smoke**: For runnable apps, add explicit startup/build/test tasks and at least one deterministic runtime smoke task before final acceptance. Use real localhost ports and project-local environments.
6. **Review And Acceptance**: Review code, tests, and run artifacts. If gaps remain, create focused fix tasks. Mark obsolete duplicates `superseded`; do not delete history. Complete the workitem only after acceptance criteria and smoke evidence are satisfied.
7. **Reporting**: Report project/workitem/workflow/task IDs, run IDs, evidence paths, commands, and final status. Mention any pending human actions or residual risks.

Default-profile orchestration rule: the `default` profile may coordinate the whole workflow, but it should not pretend separate profiles ran work they did not run. If dispatching to `designer`, `coder`, `reviewer`, or `qa`, first verify that HWE config contains those profiles, the required prompt templates exist, and each target profile has the required skills. If not dispatching, task records should use `default` or omit `--profile` and still follow the same design/implementation/check/review phases.

## Choosing Profiles And Templates

Before creating agent tasks, inspect the available HWE profiles and prompt templates, then choose from what exists. Do not invent profile names or template refs.

Use configured profiles from HWE config:

```bash
cd "$HWE_REPO"
HWE_CONFIG="$HWE_CONFIG" "$HWE_PYTHON" - <<'PY'
from hermes_workflow_engine.config import load_config
config = load_config()
print('\n'.join(sorted((config.profiles or {}).keys())))
PY
```

Profile matching rules:

- Planning, PM clarification, and technical design: prefer `designer` when available.
- Focused implementation or fix slices: prefer `coder` when available.
- Implementation review, QA review, and acceptance: prefer `reviewer`; use `qa` only for explicit QA tasks if configured.
- Deterministic shell or HTTP verification: use `command` or `http_check`, not a Hermes profile.
- Single default-chat orchestrator mode: if the user says the remote side only talks to `default`, then the default chat should create and complete HWE records itself, and task records should use `--profile default` or omit `--profile`; do not label tasks as `coder`/`reviewer` unless HWE will actually route them to those profiles.

Before assigning an agent task to another Hermes profile, verify that profile can actually see every skill the task depends on. This includes skills passed through `hwe task create --skill ...`, skills named in the prompt, and the `hwe` skill itself when that worker is expected to inspect or mutate HWE state. Do not assume `designer`, `coder`, `reviewer`, `qa`, and `default` share the same skill inventory.

If a target profile is missing a required skill, copy the complete skill directory into that profile's configured skill directory before creating or running the task. Preserve the skill's `SKILL.md`, support files, frontmatter, and relative layout. Do not create a partial copy, do not rewrite the skill for that profile, and do not overwrite a profile-local modified skill without first comparing it and preserving the newer/local changes. After copying, re-check the target profile's skill inventory or run a small profile invocation that confirms the skill is discoverable.

When driving HWE from a single `default` profile but dispatching tasks to `designer`, `coder`, `reviewer`, or `qa`, perform the skill availability check for every profile that may run a task. If the needed skill cannot be copied or verified, create a `waiting_for_info` human action instead of launching a task that is likely to fail because the worker lacks its instructions.

Choose prompt templates from project overrides first and public templates second. Public templates live under the configured `prompt_template_root`; project overrides live under `<project>/.engine/prompt-templates/`.

```bash
cd "$HWE_REPO"
HWE_CONFIG="$HWE_CONFIG" "$HWE_PYTHON" - <<'PY'
from pathlib import Path
from hermes_workflow_engine.config import load_config
config = load_config()
root = config.prompt_template_root
if root:
  for path in sorted(root.glob('*/*.md')):
    print(path.relative_to(root).with_suffix(''))
PY
```

Template selection rules:

- Planning/design tasks: use `designer/workitem-plan`, `designer/technical-design`, or `designer/task-breakdown` when present.
- Implementation tasks: use `coder/implementation-slice`; fixes use `coder/fix-slice`.
- Review/acceptance tasks: use `reviewer/implementation-review` or `reviewer/acceptance-review`.
- QA/test planning: use `qa/test-plan` or `qa/regression-review` when present.
- If no suitable template exists, create a task with explicit `--prompt-text` and say which template was missing.

## Task Kinds

Use these task kinds deliberately:

- `design`, `plan`, `review`, `qa`, `impl`, `fix`: agent tasks routed to the task's Hermes profile.
- `command`: deterministic shell command. `prompt_text` is the shell command, run from the project root.
- `http_check`: deterministic HTTP smoke test. `prompt_text` is a URL or JSON request spec.

Agent task prompts should be narrow and concrete. Coder tasks should name the slice, intended files, constraints, and verification command. Reviewer tasks should inspect code and evidence, run deterministic checks when possible, and create focused follow-up tasks rather than silently approving gaps.

## Runtime Smoke Checks

Final acceptance for runnable apps must include real runtime evidence, not static review alone.

Prefer a sequence like:

1. `command` task: install project-local backend/frontend dependencies.
2. `command` task: run backend tests or import/syntax checks.
3. `command` task: run frontend build.
4. `command` task or user-supervised terminal: start backend/frontend on explicit localhost ports.
5. `http_check` task: verify backend health, at least one API create/list/search path, and the frontend page compiles/serves expected text.
6. Reviewer final acceptance based on these logs.

Example `http_check` prompt text:

```json
{
  "requests": [
    {
      "url": "http://127.0.0.1:<backend-port>/health",
      "expect_status": 200,
      "expect_json": {"status": "healthy"}
    },
    {
      "method": "POST",
      "url": "http://127.0.0.1:<backend-port>/api/notes/",
      "json": {"title": "HWE smoke", "content": "created by http_check"},
      "expect_status": 201,
      "expect_contains": "HWE smoke"
    },
    {
      "url": "http://127.0.0.1:<frontend-port>",
      "expect_status": 200,
      "expect_contains": "Notes"
    }
  ]
}
```

`http_check` supports `method`, `headers`, `json`, `body`, `expect_status`, `expect_json`, `expect_contains`, `retries`, `retry_delay_seconds`, and `timeout_seconds`.

## Human Actions

Ask the user when requirements, acceptance criteria, ownership, external-service permissions, destructive operations, credentials, ports, data retention, or product behavior are unclear. Do not guess and do not continue with auto-run through ambiguity.

For HWE-managed work, turn uncertainty into a human action whenever the answer affects implementation or acceptance:

- If you are completing a task directly, complete it as `waiting_for_info` or `waiting_for_approval` with specific questions.
- If you are planning work, create a narrow follow-up task or human action before implementation tasks are run.
- If you are in single default-chat orchestrator mode, pause and ask the remote user directly; if the work is already represented in HWE, also record the pause as a pending HWE human action.

Good human actions include the concrete decision needed, options if known, evidence paths, and the consequence of each option. Avoid vague questions like "please clarify".

If required information or approval is missing, do not guess. Complete the task as waiting and let HWE create a human action:

```bash
hwe task complete <project> <task-id> \
  --status waiting_for_info \
  --title "Choose persistence target" \
  --body "Should notes use PostgreSQL or browser storage?" \
  --question "Where should notes be stored?" \
  --option PostgreSQL \
  --option "Local browser only"

hwe human-action list <project> --project-id <project-id> --status pending
hwe answer <project> <human-action-id> --project-id <project-id> --text "Use PostgreSQL"
```

For approvals, use `waiting_for_approval`, then `hwe approve` or `hwe reject`. Rejection marks the task failed so dependents remain blocked.

Hermes clarify timeouts are also human-action material. During headless `run-workitem`, if Hermes emits a `clarify timed out` marker and then the process hits its task timeout, HWE writes `.engine/runs/<run-id>/clarification.md`, marks the task `waiting_for_info`, and creates a pending `info_request` with `prompt.md`, `stdout.log`, `stderr.log`, and the clarification note as evidence. If the exact clarification question was not emitted by Hermes, report that plainly and use the artifacts to decide the answer, retry, or supersede path.

## Task Recovery

Preserve run history. Prefer state transitions over deleting rows, and do not treat every `claimed` task as stuck.

A task in `claimed` means a runner has acquired it. It may be actively switching models, waiting on healthcheck, running Hermes, or executing a command. Do not repeatedly release a claimed task just because it has been claimed for a while.

Before releasing a claim:

1. Inspect recent events for `task_claimed`, `task_run_started`, `task_run_finished`, and `task_completed`.
2. Inspect task runs for the task and note whether the latest run is still `started`.
3. If a run has paths, inspect `.engine/runs/<run-id>/prompt.md`, `stdout.log`, and `stderr.log`.
4. Check whether the runner process or terminal is still active if you started it.
5. Release only when there is good evidence that the runner was interrupted, crashed, or abandoned and no active process is still working on the task.

Useful inspection commands:

```bash
cd "$HWE_REPO"
export HWE_CONFIG
"$HWE" task list <project> <workflow-id>
"$HWE" project events <project> --id <project-id> --limit 30
```

If you need run details, use HWE storage with the configured backend:

```bash
cd "$HWE_REPO"
HWE_CONFIG="$HWE_CONFIG" "$HWE_PYTHON" - <<'PY'
from pathlib import Path
from hermes_workflow_engine.config import load_config
from hermes_workflow_engine.project_storage import ProjectStorage
project = '<project>'
task_id = '<task-id>'
config = load_config()
storage = ProjectStorage(config.default_workspace_root / project, config=config)
for run in storage.list_task_runs(task_id=task_id):
    print(run['id'], run['status'], run.get('stdout_path'), run.get('stderr_path'), run.get('prompt_path'))
PY
```

Abandoned claim after a confirmed cancelled/interrupted runner:

```bash
hwe task release <project> <task-id> --reason abandoned-run
```

Transient failure such as model healthcheck/server readiness:

```bash
hwe task retry <project> <task-id> --reason transient-healthcheck
```

If a runner repeatedly times out on the same agent task, do not start an endless background retry loop. Inspect logs, decide whether the task needs a narrower prompt, a longer configured timeout, model/server recovery, or a `waiting_for_info` human action.

- Duplicate or obsolete task replaced by a successful one:

```bash
hwe task complete <project> <old-task-id> \
  --status superseded \
  --result-json '{"reason":"replacement task succeeded"}'
```

Terminal dependency-satisfying statuses are `succeeded`, `skipped`, and `superseded`.

## External Services And Secrets

When the user allows use of an existing Docker/PostgreSQL service, treat it as external infrastructure:

- Do not stop, remove, recreate, rename, reconfigure, or change its ports, volumes, credentials, or environment.
- Do not hard-code external credentials in generated application code.
- Application code may require `DATABASE_URL` or `PG*` variables and provide placeholder `.env.example` values.
- HWE command tasks may create a separate project database if the user explicitly allowed that class of mutation.
- Do not print secret values. Use variable names or redacted examples in reports.

## Prompt Templates

HWE role prompt templates are Markdown files, not database records. Public source files live under the configured `prompt_template_root`, defaulting to `./ptemplate` relative to the HWE config file. Project overrides live under the target project at `.engine/prompt-templates/<role>/<name>.md`.

Tasks reference templates by `role/name`:

```bash
hwe task create <project> "$WORKFLOW_ID" "Review implementation" \
  --kind review \
  --profile reviewer \
  --prompt-template-ref reviewer/implementation-review
```

At runtime HWE reads the project override first, then falls back to `<prompt_template_root>/<role>/<name>.md`. The UI can save a file to the project or push a file to the public HWE library.

## Profile Orchestration

HWE project runtime performs profile preflight for agent tasks:

1. Run profile `switch_commands` or legacy `switch_command` if configured.
2. Run LM Studio-style `healthcheck` with retries if configured.
3. Invoke the configured Hermes command as `chat -Q --source workflow-engine -q <prompt>`.

`switch_commands` is the preferred shape for multi-step local model switches. HWE runs each command independently, records stdout/stderr, and logs a warning if a non-required command exits non-zero before continuing to the next switch step. This keeps unload/load flows tolerant when a model is already loaded or already unloaded. The legacy single-string `switch_command` still works for one-step switches. Configure `switch_command_required: true` on a profile, or `required: true` on an individual switch step, only when a failed switch must block execution.

Hermes hook and dangerous-command approval prompts are handled by Hermes, not by HWE human actions. For trusted local profiles, set `hooks_auto_accept: true` in the Hermes profile config or configure `hermes_args: [--accept-hooks]`; do not use `--yolo` for routine HWE runs. HWE closes agent stdin so unexpected interactive prompts fail or receive EOF instead of hanging until timeout.

`task_run_started` events include the `run_id`. Active runs should have stdout/stderr/prompt paths under `.engine/runs/<run-id>/` so the UI/API can inspect logs while a task is still running.

If a profile has an observed non-zero successful shutdown code, configure it in HWE local config with `success_exit_codes`. For example, Qwen coder may return `-6` after useful completion.

Do not add model switching commands to generated projects or task prompts when HWE profile config can own them.

## Output Expectations

When working as designer/reviewer inside HWE:

- State which project, workitem, workflow, and task IDs were used.
- Create focused tasks rather than broad all-in-one coder prompts.
- Include deterministic verification tasks for risky or runnable changes.
- Record evidence paths, run IDs, commands, URLs, and observed outcomes.
- If rejecting or requesting fixes, create or recommend the smallest next coder/fix task.

When working as coder inside HWE:

- Only implement the assigned slice.
- Keep changes inside the project root and declared scope.
- Do not modify HWE itself unless the task is explicitly an HWE repository task.
- Run the requested verification command if practical and report exact results.