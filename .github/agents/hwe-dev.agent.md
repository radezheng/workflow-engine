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
- Project workflow mode: project-local `.engine/engine.db` stores projects, workitems, workflows, tasks, task runs, human actions, prompt templates, and events. This is the primary direction for future API/UI work.

Important design rules:

- A project is the real workspace folder. Each project owns its own `.engine/` directory.
- A workitem is the user-facing unit of delivery.
- A workflow is the current execution strategy for one workitem.
- A task is the worker-facing unit of execution.
- Planner/reviewer profiles own planning, design, QA, test design, and acceptance.
- Coder profile writes code and fixes only focused slices.
- Command and `http_check` tasks are deterministic verification surfaces.
- Model switching and health checks belong in HWE profile preflight, not in generated projects or skills.
- External services such as an existing Docker/PostgreSQL container are external infrastructure; do not mutate their lifecycle, credentials, ports, volumes, or container config unless explicitly requested.
- Machine-specific defaults live in `hwe.config.yaml`, which is local and gitignored.

## Main Files

- `src/hermes_workflow_engine/cli.py`: CLI wiring. Static commands are `validate`, `run`, `status`, `events`. Project commands include `project`, `workitem`, `workflow`, `task`, `prompt-template`, `human-action`, `answer`, `approve`, `reject`, and `run-workitem`.
- `src/hermes_workflow_engine/project_storage.py`: Project/workitem/workflow/task persistence and state transitions. This is where task readiness, claims, retry/release, terminal statuses, human actions, role prompt templates, and events live.
- `src/hermes_workflow_engine/project_runtime.py`: Push-style project runner. Claims ready tasks, builds prompts, runs command/http_check/agent tasks, performs profile preflight, writes run logs, completes tasks, and returns run summaries.
- `src/hermes_workflow_engine/config.py`: HWE-local config discovery and parsing. Owns `default_workspace_root`, `prompt_template_root`, and per-profile config.
- `src/hermes_workflow_engine/spec.py`: Static YAML workflow spec parsing.
- `src/hermes_workflow_engine/runtime.py`: Static workflow runtime.
- `src/hermes_workflow_engine/storage.py`: Static workflow storage and shared helpers such as `now_iso`.
- `src/hermes_workflow_engine/context.py`: Static-mode context bundle assembly helpers.
- `src/hermes_workflow_engine/worker.py`: Static-mode Hermes worker adapter helpers.
- `src/hermes_workflow_engine/validators.py`: Deterministic validators/gates for static workflow mode.
- `src/hermes_workflow_engine/__main__.py`: `python -m hermes_workflow_engine` entrypoint.
- `src/hermes_workflow_engine/__init__.py`: Package metadata surface.
- `schema/engine_schema.sql`: Installable SQLite schema for project workflow state. Keep it compatible with `ProjectStorage.initialize()`.
- `README.md`: User-facing CLI and behavior docs. Update for new commands, task kinds, config keys, and recovery flows.
- `workflow_engine_design.md`: Original engine architecture and static workflow design.
- `workflow_engine_project_design.md`: Project/workitem/task queue design and API/UI direction.
- `ptemplate/`: HWE-side role prompt template source root. Relative to `hwe.config.yaml`, not to target projects.
- `tests/test_engine.py`: Static workflow/config tests.
- `tests/test_project_storage.py`: Project storage, CLI, runtime, preflight, task recovery, and smoke-check tests.

## Current Project Workflow Capabilities

Storage and CLI currently support:

- Project init/show/events.
- Workitem create/list.
- Workflow create.
- Task create/list/claim/complete/release/retry.
- Task statuses: `pending`, `ready`, `claimed`, `waiting_for_info`, `waiting_for_approval`, `succeeded`, `failed`, `cancelled`, `skipped`, `superseded`.
- Terminal dependency-satisfying statuses: `succeeded`, `skipped`, `superseded`.
- Human actions: information requests and approval requests, resolved through `answer`, `approve`, and `reject`.
- Role prompt templates loaded from `prompt_template_root` when no body is passed.
- `run-workitem` push-style execution for one or more ready tasks.

Runtime task kinds:

- `command`: `prompt_text` is a shell command run from the project root.
- `http_check`: `prompt_text` is a URL or JSON request spec. Supports method, headers, JSON/body, expected HTTP status, expected JSON fields, expected text, retries, delay, and timeout.
- Any other kind is treated as an agent task and routed through Hermes profile invocation.

Agent task flow:

1. Create a task run and `.engine/runs/<run-id>/`.
2. Build `prompt.md` from role template, task prompt, workitem requirements/constraints, skills, outputs, and gates.
3. Run profile `switch_command` if configured.
4. Run LM Studio-style healthcheck if configured, with retries.
5. Invoke `hermes_command` or profile alias as `chat -Q --source workflow-engine -q <prompt>`.
6. Record stdout, stderr, exit code, result, and task completion.

## Local Config Shape

Typical local `hwe.config.yaml`:

```yaml
default_workspace_root: /Users/rade/workspaces/hermes
prompt_template_root: ./ptemplate
profiles:
  coder:
    hermes_profile: coder
    hermes_command: coder
    success_exit_codes: [0, -6]
    switch_command: lms unload --all && lms load qwen/qwen3-coder-next --identifier qwen/qwen3-coder-next --yes
    healthcheck:
      url: http://127.0.0.1:1234/v1/chat/completions
      model: qwen/qwen3-coder-next
      retries: 5
      retry_delay_seconds: 2
  reviewer:
    hermes_profile: reviewer
    hermes_command: reviewer
    switch_command: lms unload --all && lms load gemma-4-31b-it-mlx@6bit --identifier gemma-4-31b-it-mlx@6bit --yes
    healthcheck:
      url: http://127.0.0.1:1234/v1/chat/completions
      model: gemma-4-31b-it-mlx@6bit
```

Do not hard-code these local values into tracked source or generated projects. Use them only as examples when explaining config behavior.

## Dogfood Lessons To Preserve

- Static reviewer QA missed actual runtime failures. Final acceptance for runnable apps should include deterministic runtime smoke tasks, ideally `kind=http_check`, plus real backend/frontend startup commands.
- Qwen coder can return `-6` after useful completion. Use profile `success_exit_codes` rather than treating every non-zero shutdown as failure.
- LM Studio may return transient 400 immediately after switching models. Healthcheck retry exists for this reason.
- Push-style runner can be interrupted. Use `hwe task release <project> <task-id> --reason cancelled-run` for abandoned claims.
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

When changing schema:

- Update `schema/engine_schema.sql`.
- Ensure `ProjectStorage.initialize()` remains idempotent.
- Add tests that initialize a fresh project and exercise the new fields.

When changing architecture , design or operating rules:

- Update `README.md` if the design intent changes.
- Update `README.md` for user-facing CLI, config, task kind, recovery, or verification changes.
- Update `/Users/rade/.hermes/skills/hwe/SKILL.md` when Hermes workers need new guidance.
- Update `.github/agents/hwe-dev.agent.md` when Copilot agents need new repository map, invariants, or change patterns.
- Keep these docs concise and aligned; do not let the skill preserve obsolete Kanban/project-template instructions.

## Verification Commands

Use these from the repo root:

```bash
.venv/bin/pytest
.venv/bin/hwe config show
.venv/bin/hwe task list <project> <workflow-id>
.venv/bin/hwe run-workitem <project> <workitem-id> --project-id <project-id> --max-tasks 1
```

For generated app dogfood, prefer project-local environments and explicit ports. Do not commit generated dependencies, local env files, `.engine/`, `node_modules/`, `.next/`, `.venv/`, caches, or secrets.

## Output Style

When reporting back, lead with what changed and whether tests passed. Mention any generated-project fixes separately from HWE changes. If services are left running, include their localhost URLs and terminal/process context.