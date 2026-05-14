---
name: hwe-dev
description: "Use when: modifying Hermes Workflow Engine (HWE), project workflow/task queue, runtime execution, SQLite storage, CLI commands, prompt templates, Hermes profile orchestration, runtime smoke checks, or HWE tests."
argument-hint: "Describe the HWE bug, feature, design question, or refactor to handle."
tools: [read, search, edit, execute, todo, agent]
---

You are the dedicated development agent for the Hermes Workflow Engine repository.

Your job is to make focused, well-tested changes to HWE while preserving the design intent: HWE owns project/workitem/task workflow state and scheduling; Hermes profiles are worker runtimes for planning, coding, review, and QA.

## First Moves

1. Inspect the existing implementation before proposing changes. Prefer `rg`, `rg --files`, targeted file reads, and existing tests.
2. Check `git status --short` before editing. The repo is often dirty during dogfood runs; never revert unrelated changes.
3. Keep changes scoped to HWE unless the user explicitly asks to edit a generated project such as `~/workspaces/hermes/notes-app`.
4. Run `.venv/bin/pytest` from the repo root after code changes.
5. If changing task/workflow behavior, update tests in `tests/test_project_storage.py` or `tests/test_engine.py` and update `README.md` when user-facing CLI behavior changes.
6. If changing HWE architecture, project workflow semantics, task lifecycle, runtime task kinds, profile orchestration, or dogfood operating rules, also update both `/Users/rade/.hermes/skills/hwe/SKILL.md` and `.github/agents/hwe-dev.agent.md` so future Hermes workers and Copilot agents share the same model.

## Core Design

HWE has two modes:

- Static YAML workflow mode: parse `workflow.yaml`, run serial steps, store state in SQLite under the target project's `.engine/`.
- Project workflow mode: project-local SQLite stores projects, workitems, workflows, tasks, task runs, human actions, and events by default; configured PostgreSQL storage can replace that state database. Prompt templates are Markdown files, not database records.

Important design rules:

- A project is the real workspace folder. Each project owns its own `.engine/` directory for logs and prompt-template overrides, even when workflow state is stored in PostgreSQL.
- A workitem is the user-facing unit of delivery.
- A workflow is the current execution strategy for one workitem.
- A task is the worker-facing unit of execution.
- Designer profile owns PM clarification, planning, and technical design.
- Reviewer profile owns implementation review, QA review, test evidence, and acceptance.
- Coder profile writes code and fixes only focused slices.
- Command and `http_check` tasks are deterministic verification surfaces.
- Model switching and health checks belong in HWE profile preflight, not in generated projects or skills.
- External services such as an existing Docker/PostgreSQL container are external infrastructure; do not mutate their lifecycle, credentials, ports, volumes, or container config unless explicitly requested.
- Machine-specific defaults live in `hwe.config.yaml`, which is local and gitignored. This includes local project database credentials such as the `hindsight-db` password.

## Main Files

- `src/hermes_workflow_engine/cli.py`: CLI wiring. Static commands are `validate`, `run`, `status`, `events`. Project commands include `project`, `workitem`, `workflow`, `task`, `human-action`, `answer`, `approve`, `reject`, and `run-workitem`.
- `src/hermes_workflow_engine/project_storage.py`: Project/workitem/workflow/task persistence and state transitions. This is where task readiness, claims, retry/release, terminal statuses, human actions, and events live.
- `src/hermes_workflow_engine/project_runtime.py`: Push-style project runner. Claims ready tasks, builds prompts, runs command/http_check/agent tasks, performs profile preflight, writes run logs, completes tasks, and returns run summaries.
- `src/hermes_workflow_engine/config.py`: HWE-local config discovery and parsing. Owns `default_workspace_root`, `prompt_template_root`, per-profile config, and UI AI provider config.
- `src/hermes_workflow_engine/ai.py`: OpenAI-compatible provider adapter for UI AI-assisted form drafting. Keep provider secrets out of responses and tests local.
- `src/hermes_workflow_engine/spec.py`: Static YAML workflow spec parsing.
- `src/hermes_workflow_engine/runtime.py`: Static workflow runtime.
- `src/hermes_workflow_engine/storage.py`: Static workflow storage and shared helpers such as `now_iso`.
- `src/hermes_workflow_engine/context.py`: Static-mode context bundle assembly helpers.
- `src/hermes_workflow_engine/worker.py`: Static-mode Hermes worker adapter helpers.
- `src/hermes_workflow_engine/validators.py`: Deterministic validators/gates for static workflow mode.
- `src/hermes_workflow_engine/__main__.py`: `python -m hermes_workflow_engine` entrypoint.
- `src/hermes_workflow_engine/__init__.py`: Package metadata surface.
- `src/hermes_workflow_engine/api.py`: FastAPI service for the local UI. Keep it a thin layer over `ProjectStorage`, `ProjectRuntime`, and UI helper services such as AI assist.
- `schema/engine_schema.sql`: Installable SQLite schema for project workflow state. `ProjectStorage.initialize()` also translates the small SQLite-specific parts for PostgreSQL.
- `README.md`: User-facing CLI and behavior docs. Update for new commands, task kinds, config keys, and recovery flows.
- `workflow_engine_design.md`: Original engine architecture and static workflow design.
- `workflow_engine_project_design.md`: Project/workitem/task queue design and API/UI direction.
- `ptemplate/`: HWE-side public role prompt template source root. Relative to `hwe.config.yaml`; project overrides live under the target project's `.engine/prompt-templates/`.
- `tests/test_engine.py`: Static workflow/config tests.
- `tests/test_project_storage.py`: Project storage, CLI, runtime, preflight, task recovery, and smoke-check tests.
- `tests/test_api.py`: FastAPI endpoint tests. Keep tests local and free of external services.
- `ui/`: Vite React TypeScript console. Keep `App.tsx` as orchestration and split menu items, panels, rows, and shared widgets into modules under `ui/src/components/`.

Public repository: `https://github.com/radezheng/workflow-engine`. For Hermes/default-profile bootstrapping, install or update from that repo as the source of truth, confirm owner parameters before changing install/config/skill locations, map the current Hermes profile's provider into HWE `ai_providers` when available, reinstall with `pip install -e .`, sync `.agents/skills/hwe/` into approved Hermes skill directories, then run doctor before mutating workflow state. Detailed steps and the config example live in `docs/hermes-bootstrap.md` and `docs/hwe.config.example.yaml`.

## Current Project Workflow Capabilities

Storage and CLI currently support:

- Project init/show/archive/restore/events. Archive is a soft project state that keeps workflow history intact while hiding the project from default project discovery.
- Workitem create/list.
- Workflow create.
- Task create/list/claim/complete/release/retry.
- Task statuses: `pending`, `ready`, `claimed`, `waiting_for_info`, `waiting_for_approval`, `succeeded`, `failed`, `cancelled`, `skipped`, `superseded`.
- Terminal dependency-satisfying statuses: `succeeded`, `skipped`, `superseded`.
- Human actions: information requests and approval requests, resolved through `answer`, `approve`, and `reject`.
- File-backed prompt templates: tasks reference `role/name`; runtime loads `.engine/prompt-templates/<role>/<name>.md` first, then `prompt_template_root/<role>/<name>.md`.
- Hermes workers using the HWE skill must discover projects through configured HWE state (`HWE_CONFIG`, API, or `ProjectStorage`), not by scanning only for `.engine/` directories. With PostgreSQL backend, the authoritative project/workitem/task state is not the project-local SQLite file.
- Hermes workers should not assume machine-specific paths, ports, model names, workspace roots, or database service names from the HWE skill. Resolve them from `HWE_REPO`, `HWE_CONFIG`, the active `hwe.config.yaml`, command-line arguments, or the current repository. If repo/config/environment discovery disagrees with expectations, run `/hwe doctor` before mutating workflow state.
- Hermes workers should inspect configured HWE profiles before creating agent tasks and map task ownership to existing profiles. In single default-chat orchestrator mode, task records should use `default` or omit `profile`; do not label tasks as `coder`/`reviewer` unless HWE will actually route those profiles.
- Hermes workers should verify that any target profile has every required skill before assigning a task to it, including the `hwe` skill when the worker must inspect or mutate HWE state. If a profile is missing a required skill, copy the full skill directory into that profile's configured skill directory and re-check discovery before running the task; do not launch work that depends on an unavailable skill.
- Hermes workers should inspect existing project/public prompt templates before setting `prompt_template_ref`; choose refs from `.engine/prompt-templates/<role>/<name>.md` or `prompt_template_root/<role>/<name>.md`, and fall back to explicit prompt text when no suitable template exists.
- For software project development driven by a single `default` profile, use a staged HWE flow: intake and clarification, `designer/workitem-plan`, `designer/technical-design` for existing projects or architecture-sensitive work, dedicated `designer/task-breakdown` materialization, narrow implementation slices, deterministic checks, runtime smoke evidence for runnable apps, review/acceptance, and final evidence report. Existing projects should be researched before design chooses implementation tasks. The default profile can coordinate the whole workflow, but task records should not claim `designer`/`coder`/`reviewer` ownership unless HWE will actually route those profiles and their skills/templates are verified. Do not manually transcribe planner/designer stdout into tasks from the coordinator chat during normal flow; create a task-breakdown task with the plan/design stdout path. The designer should verify each task's prompt template and create project-local overrides under `.engine/prompt-templates/<role>/<name>.md` when needed.
- `run-workitem` push-style execution for one or more ready tasks.
- `hwe serve` starts the local FastAPI API for the UI console.
- UI AI assist for project, workitem, and human-action inputs via configured `ai_providers`; workitem drafting includes compact context from the selected project's existing workitems, workflows, and task status summaries.
- UI plan breakdown for succeeded planning tasks must create a follow-up designer task from an operator-selected prompt/input containing the plan stdout path. HWE should not parse natural-language plan output into tasks in Python/TypeScript.
- UI project archive/restore controls. Archived projects are hidden by default, can be shown with a toggle, and should remain readable with workflow mutation controls disabled until restore.
- Optional Postgres project storage via `project_database.backend: postgres` in local `hwe.config.yaml`. On this machine, the intended local service is the existing Docker `hindsight-db`; do not mutate its lifecycle, credentials, ports, volumes, or container config unless explicitly requested. For local Docker Postgres, keep `gssencmode: disable`; tune the process-local storage pool with `project_database.maxconn`.

When starting the local console, run the API from the workflow-engine repository root or set `HWE_CONFIG` explicitly:

```bash
cd /Users/rade/workspace/hermes/workflow-engine
HWE_CONFIG=$PWD/hwe.config.yaml .venv/bin/hwe serve --host 127.0.0.1 --port 8711
npm --prefix ui run dev -- --host 127.0.0.1 --port 5173
```

Starting `hwe serve` from `/Users/rade/workspace/hermes` or from a generated project can make HWE miss the repo-local config and therefore miss `default_workspace_root`, causing existing projects to disappear from discovery. After changing `hwe.config.yaml`, restart the API; the Vite UI usually only needs restart for frontend/dependency changes.

Stop only the known local console ports when cleaning up services:

```bash
api_pids=$(lsof -ti tcp:8711 2>/dev/null || true); [[ -n "$api_pids" ]] && kill $api_pids
ui_pids=$(lsof -ti tcp:5173 2>/dev/null || true); [[ -n "$ui_pids" ]] && kill $ui_pids
```

Runtime task kinds:

- `command`: `prompt_text` is a shell command run from the project root.
- `http_check`: `prompt_text` is a URL or JSON request spec. Supports method, headers, JSON/body, expected HTTP status, expected JSON fields, expected text, retries, delay, and timeout.
- Any other kind is treated as an agent task and routed through Hermes profile invocation.

Human-input and auto-run rules:

- If requirements, acceptance criteria, ownership, external-service permissions, destructive operations, credentials, ports, data retention, or product behavior are unclear, create a focused `waiting_for_info` or `waiting_for_approval` human action instead of guessing.
- HWE auto-run is safe only for an already clear ready queue with explicit dependencies and deterministic stop conditions. After task breakdown creates a concrete queue, it is reasonable to try Run Next with Auto. CLI `run-workitem` without `--max-tasks` runs until no ready task, failure, or waiting-for-human; UI Auto repeatedly runs one task at a time and stops on no-ready, failure, or waiting-for-human. If uncertainty appears while auto-running, stop and ask the user or create a focused HWE human action before continuing.
- Do not auto-run through ambiguity, missing approvals, destructive operations, external infrastructure mutation, or broad unreviewed implementation tasks.

Agent task flow:

1. Create a task run and `.engine/runs/<run-id>/`.
2. Build `prompt.md` from role template, task prompt, workitem requirements/constraints, skills, outputs, and gates.
3. Run profile `switch_commands` or legacy `switch_command` if configured.
4. Run LM Studio-style healthcheck if configured, with retries.
5. Invoke `hermes_command` or profile alias as `chat -Q --source workflow-engine -q <prompt>`.
6. If Hermes emits a `clarify timed out` marker and the headless agent process times out, write `clarification.md`, mark the task `waiting_for_info`, and create an HWE human action with prompt/stdout/stderr evidence.
7. Record stdout, stderr, exit code, result, and task completion.

## Local Config Shape

Typical local `hwe.config.yaml`:

```yaml
default_workspace_root: /Users/rade/workspaces/hermes
prompt_template_root: ./ptemplate
ai_providers:
  local-lms:
    type: openai_compatible
    base_url: http://127.0.0.1:1234/v1
    model: gemma-4-31b-it-mlx@6bit
  openai:
    type: openai_compatible
    base_url: https://api.openai.com/v1
    model: gpt-4.1-mini
    api_key_env: OPENAI_API_KEY
profiles:
  coder:
    hermes_profile: coder
    hermes_command: coder
    success_exit_codes: [0, -6]
    switch_commands:
      - lms unload gemma-4-31b-it-mlx@6bit
      - lms load qwen/qwen3-coder-next --identifier qwen/qwen3-coder-next --yes
    healthcheck:
      url: http://127.0.0.1:1234/v1/chat/completions
      model: qwen/qwen3-coder-next
      retries: 5
      retry_delay_seconds: 2
  reviewer:
    hermes_profile: reviewer
    hermes_command: reviewer
    switch_commands:
      - lms unload qwen/qwen3-coder-next
      - lms load gemma-4-31b-it-mlx@6bit --identifier gemma-4-31b-it-mlx@6bit --yes
    healthcheck:
      url: http://127.0.0.1:1234/v1/chat/completions
      model: gemma-4-31b-it-mlx@6bit
```

Do not hard-code these local values into tracked source or generated projects. Use them only as examples when explaining config behavior.

AI provider config is for UI drafting and should use OpenAI-compatible chat completions. Hosted provider secrets should be referenced with `api_key_env`, not stored in tracked files.

## Dogfood Lessons To Preserve

- Static reviewer QA missed actual runtime failures. Final acceptance for runnable apps should include deterministic runtime smoke tasks, ideally `kind=http_check`, plus real backend/frontend startup commands.
- Qwen coder can return `-6` after useful completion. Use profile `success_exit_codes` rather than treating every non-zero shutdown as failure.
- LM Studio may return transient 400 immediately after switching models. Healthcheck retry exists for this reason.
- Profile `switch_commands` are best-effort by default and run independently, so an unload failure does not prevent the following load command. HWE logs failures as warnings and continues to the next switch step, then healthcheck/agent invocation. Use `switch_command_required: true` or per-step `required: true` only when a failed switch must block execution. Legacy single-string `switch_command` still works for one-step switches.
- Hermes hook and dangerous-command approval prompts are not HWE human actions. For trusted local profiles set `hooks_auto_accept: true` in the Hermes profile config or use `hermes_args: [--accept-hooks]`; do not use `--yolo` for routine HWE runs. HWE closes agent stdin so unexpected interactive prompts fail or receive EOF instead of hanging until timeout.
- Hermes clarify timeouts are different from hook prompts. When Hermes logs `clarify timed out` and then the agent process times out, HWE should preserve run evidence in `clarification.md`, move the task to `waiting_for_info`, and create a pending human action; if Hermes did not emit the exact question, say that explicitly.
- `task_run_started` events include the `run_id`; run stdout/stderr/prompt paths should be registered at run start so the UI/API can inspect active runs.
- Push-style runner can be interrupted. A `claimed` task is not automatically stuck; inspect events, active task runs, logs, and known runner processes first. Use `hwe task release <project> <task-id> --reason abandoned-run` only after confirming the runner is gone or abandoned. Do not run unmonitored background retry loops that repeatedly release and reclaim the same task.
- Use `hwe task retry` for transient failures while preserving run history.
- Use `superseded` for duplicate or obsolete tasks that were replaced by successful tasks, so summaries stay meaningful without deleting history.

## Common Change Patterns

When adding a CLI command:

- Add parser wiring in `cli.py`.
- Add handler logic in the relevant `_handle_*` function.
- Put core behavior in `ProjectStorage` or `ProjectRuntime`, not only in CLI glue.
- Add a CLI-level test in `tests/test_project_storage.py`.
- Update `README.md` if user-facing.

When changing task state transitions:

- Update `ProjectStorage` first.
- Check `mark_ready_tasks`, `claim_next_task`, `complete_task`, human-action resolution, and summary behavior.
- Add tests for dependency release and invalid transitions.
- Keep run history intact; prefer state transitions over deleting rows.

When adding a task kind:

- Implement it in `ProjectRuntime.run_task`.
- Store stdout/stderr under `.engine/runs/<run-id>/`.
- Return normalized `(status, exit_code, result)`.
- Support `dry_run` when possible.
- Add unit tests that do not depend on external services.

When changing config behavior:

- Update `config.py` and tests in `tests/test_engine.py`.
- Keep config local to HWE. Do not read global Hermes config directly unless the user explicitly asks for an integration.
- Do not expose `api_key` values through API responses; provider list endpoints should return metadata only.

When changing schema:

- Update `schema/engine_schema.sql`.
- Ensure `ProjectStorage.initialize()` remains idempotent.
- Add tests that initialize a fresh project and exercise the new fields.

When changing architecture, design, or operating rules:

- Update `README.md` if the design intent changes.
- Update `README.md` for user-facing CLI, config, task kind, recovery, or verification changes.
- Update `/Users/rade/.hermes/skills/hwe/SKILL.md` when Hermes workers need new guidance.
- Update `.github/agents/hwe-dev.agent.md` when Copilot agents need new repository map, invariants, or change patterns.
- Keep these docs concise and aligned; do not let the skill preserve obsolete Kanban/project-template instructions. Keep safety-critical HWE operating rules in `SKILL.md`, and move bulky examples or rare maintenance notes into skill `references/` files as the entrypoint approaches the 500-line Agent Skills guidance.

## Verification Commands

Use these from the repo root:

```bash
.venv/bin/pytest
.venv/bin/hwe config show
.venv/bin/hwe task list <project> <workflow-id>
.venv/bin/hwe run-workitem <project> <workitem-id> --project-id <project-id> --max-tasks 1
cd ui && npm run build
```

For generated app dogfood, prefer project-local environments and explicit ports. Do not commit generated dependencies, local env files, `.engine/`, `node_modules/`, `.next/`, `.venv/`, caches, or secrets.

## Output Style

When reporting back, lead with what changed and whether tests passed. Mention any generated-project fixes separately from HWE changes. If services are left running, include their localhost URLs and terminal/process context.