---
name: hwe
description: "Use when: driving work through Hermes Workflow Engine (HWE), running hwe doctor config/environment checks, creating/editing workflow templates, operating project/workitem/workflow/task queues, using hwe run-workitem, handling human actions, prompt templates, task retry/release/superseded, runtime smoke checks, local Hermes profile orchestration, or external PostgreSQL/Docker safety."
argument-hint: "[doctor|workflow-template|project/workitem/task operation]"
version: 0.1.0
metadata:
  hermes:
    tags: [hwe, workflow-engine, workflow-template, task-queue, qa, runtime-smoke, postgres, safety]
    related_skills: []
---

# HWE: Hermes Workflow Engine

Use this skill when work should be represented and executed through HWE instead of ad hoc chat. HWE owns project/workitem/workflow/task state and scheduling; Hermes profiles are worker runtimes.

Public repository: `https://github.com/radezheng/workflow-engine`

Keep this entrypoint concise. Put bulky examples and template-design details in references such as [workflow-template-authoring](./references/workflow-template-authoring.md) and [skill-maintenance](./references/skill-maintenance.md).

## Bootstrap, Update, And Skill Sync

When the user asks to install HWE, update HWE from the public repo, refresh the local CLI, or reinstall/sync the `hwe` skill into Hermes profiles, follow `$HWE_REPO/docs/hermes-bootstrap.md`. The public repository is the source of truth; do not treat an old copied skill directory or unverified local checkout as authoritative.

Maintenance flow, in brief:

1. Confirm owner-approved repo path, config path, Hermes skill directories, and whether existing skill copies may be overwritten.
1. Clone or update `https://github.com/radezheng/workflow-engine` in the approved `HWE_REPO`.
1. Reinstall locally with the repo virtualenv, normally `python -m pip install -e .`.
1. Sync the full `.agents/skills/hwe/` directory into every approved Hermes user/profile skill directory; preserve `SKILL.md`, `scripts/`, `references/`, frontmatter, and relative layout.
1. Run `hwe doctor --repo "$HWE_REPO" --config "$HWE_CONFIG"` before mutating workflow state.

Ask before changing credentials, ports, database/container lifecycle, schemas, profile commands, model switch commands, API/UI service lifecycle, or overwriting profile-local skill customizations.

## Operating Contract

- Resolve HWE repo/config before mutation. Use `HWE_REPO`, `HWE_CONFIG`, active `hwe.config.yaml`, command arguments, or the current repository; do not assume machine-specific paths, ports, model names, database services, or workspace roots.
- Discover projects through configured HWE state (`HWE_CONFIG`, API, or `ProjectStorage`), not by scanning for `.engine/` directories. PostgreSQL can be the authoritative state store.
- If the user is asking how a workflow should be structured, create or edit a workflow template first. Do not encode a one-off workflow in this skill or by manually transcribing plan prose into tasks.
- When operating a workitem, follow the selected workflow template's API-reported stages, dependencies, gates, materialization source rules, and actions. The template is the source of flow truth.
- Verify configured profiles, prompt template refs, and target-profile skill availability before creating agent tasks.
- Convert unclear requirements, approvals, destructive operations, credentials, ports, data retention, external-service permissions, or product behavior into HWE human actions instead of guessing.
- Keep runners visible. Do not start competing runners for the same workitem, and do not run unmonitored background retry loops.

## Core Model

- **Project**: a real workspace folder. It owns `.engine/` logs and project overrides even when workflow state is stored in PostgreSQL.
- **Workitem**: the user-facing unit of delivery.
- **Workflow**: the current execution strategy for one workitem.
- **Task**: the worker-facing unit of execution. Tasks are narrow, auditable, dependency-aware records.
- **Workflow template**: YAML flow definition for profiles, prompt-template refs, planning/materialization task specs, source rules, gates, parameters, and child workflows. Built-ins ship with HWE; config templates live under `workflow_template_root`; project overrides live under `.engine/workflow-templates/`.
- **Prompt template**: Markdown role prompt file under `prompt_template_root` or `.engine/prompt-templates/`. Prompt templates describe worker behavior; workflow templates decide flow.

## First Checks

Run these before mutating project workflow state:

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

If project discovery disagrees with expectations, run doctor before changing state:

```bash
"$HWE" doctor --repo "$HWE_REPO" --config "$HWE_CONFIG"
```

Use `--fix` only for safe local directory creation. Ask before changing credentials, ports, database/container lifecycle, schemas, profile commands, model switch commands, service lifecycle, or existing profile-local skills.

## Workflow Template Work

Before creating a new queue shape, inspect available templates:

```bash
HWE_API_URL=${HWE_API_URL:-http://127.0.0.1:${HWE_API_PORT:-8711}}
curl -sS "$HWE_API_URL/api/projects/<project>/workflow-templates?project_id=<project-id>"
```

If no template matches the work, create or edit a workflow template YAML file first. Use [workflow-template-authoring](./references/workflow-template-authoring.md) for schema, validation, and override rules.

Template location priority:

1. Built-in package templates: `src/hermes_workflow_engine/workflow_templates/`
2. Config-level templates: `workflow_template_root`
3. Project-local overrides: `<project>/.engine/workflow-templates/`

After editing a template, verify it through the API or storage loader, and restart `hwe serve` if the API is already running.

## Project And Workitem Operation

Prefer the UI/API for template-driven planning because the API resolves template parameters, creates template-defined planning/gate tasks, and exposes materialization actions only for valid source tasks.

Use this advancement loop for an existing workitem:

1. Refresh state from the workitem dashboard, not from memory.
1. Resolve pending human actions first; if a standalone answer unlocks work, create or run the concrete continuation task.
1. If no current workflow exists, plan the workitem with the selected workflow template.
1. If any task exposes `workflow_actions`, take the API-reported action before inventing manual next steps.
1. If ready tasks exist, run one task, then refresh the dashboard before deciding again.
1. If there are no ready tasks, no workflow actions, and no pending human actions, report the terminal status and evidence instead of creating extra tasks.
1. If progress is blocked by missing requirements, approval, profile/template mismatch, runner failure, or external-service risk, stop and create a human action or recovery task.

Dashboard state:

```bash
curl -sS "$HWE_API_URL/api/projects/<project>/workitems/<workitem-id>/dashboard?project_id=<project-id>"
```

Plan a workitem through a selected template:

```bash
curl -sS -X POST "$HWE_API_URL/api/projects/<project>/workitems/<workitem-id>/plan" \
  -H 'content-type: application/json' \
  -d '{"project_id":"<project-id>","workflow_template_id":"<template-id>","parameters":{}}'
```

Run ready tasks one at a time while dogfooding or debugging:

```bash
"$HWE" run-workitem <project> <workitem-id> --project-id <project-id> --max-tasks 1
```

Materialize only through an API-reported workflow action. Do not infer materialization eligibility from task title, kind, or prompt-template ref.

```bash
curl -sS -X POST "$HWE_API_URL/api/projects/<project>/tasks/<source-task-id>/materialize-plan" \
  -H 'content-type: application/json' \
  -d '{"project_id":"<project-id>","workflow_template_id":"<template-id>","parameters":{}}'
```

## Profiles, Skills, And Prompts

Profiles route agent tasks; they are not merely labels. Before assigning an agent task:

1. Inspect configured HWE profiles from `hwe.config.yaml`.
2. Confirm the prompt template ref exists in project overrides or `prompt_template_root`.
3. Confirm the target Hermes profile can discover every required skill, including `hwe` when the worker must inspect or mutate HWE state.
4. If routing through one `default` profile, use template parameters or `default`/no profile task records; do not pretend `designer`, `coder`, or `reviewer` ran work they will not actually run.

Profile responsibility defaults:

- Designer: PM clarification, planning, technical design.
- Coder: focused implementation or fix slices only.
- Reviewer: implementation review, QA review, test evidence, acceptance.
- Deterministic verification: use `command` or `http_check`, not a Hermes profile.

## Human Actions

Use real HWE human actions for uncertainty. Never create fake `kind=human-action` tasks.

```bash
"$HWE" human-action create <project> "Confirm decision" \
  --project-id <project-id> \
  --workitem-id <workitem-id> \
  --workflow-id <workflow-id> \
  --body "State the decision needed and why it blocks progress." \
  --question "What should HWE do next?" \
  --option "Option A" \
  --option "Option B" \
  --requested-by <profile>
```

A pending human action attached to a workitem or its current workflow blocks the workitem as `waiting_for_human`. Task-linked actions move the waiting task back to `ready` when answered or approved. Standalone actions only record the decision; the requesting worker must create or run a concrete continuation task.

Hermes clarify timeouts are human-action material. If headless Hermes logs `clarify timed out` and the process times out, HWE preserves run evidence, marks the task `waiting_for_info`, and creates a pending human action.

## Running And Recovery

Task statuses are `pending`, `ready`, `running`, `waiting_for_info`, `waiting_for_approval`, `succeeded`, `failed`, `cancelled`, `skipped`, and `superseded`. `claimed` is only an internal lease concept, not a user-facing task status.

Before releasing a `running` task:

1. Inspect events for `task_running`, `task_run_started`, `task_run_finished`, and `task_completed`.
2. Inspect task runs and `.engine/runs/<run-id>/prompt.md`, `stdout.log`, and `stderr.log` when present.
3. Check whether the runner process or terminal is still active if you started it.
4. Release only when there is evidence the runner was interrupted, crashed, or abandoned.

Useful recovery commands:

```bash
"$HWE" project events <project> --id <project-id> --limit 30
"$HWE" task release <project> <task-id> --reason abandoned-run
"$HWE" task retry <project> <task-id> --reason transient-healthcheck
"$HWE" task complete <project> <old-task-id> --status superseded --result-json '{"reason":"replacement task succeeded"}'
```

Terminal dependency-satisfying statuses are `succeeded`, `skipped`, and `superseded`.

## Runtime Verification

Final acceptance for runnable apps needs deterministic evidence when practical:

- `command` tasks for install/build/tests/startup checks.
- `http_check` tasks for health endpoints and representative runtime paths.
- Reviewer acceptance based on run IDs, logs, commands, URLs, and observed outcomes.

`http_check` prompt text can be a URL or JSON request spec with `method`, `headers`, `json`, `body`, `expect_status`, `expect_json`, `expect_contains`, `retries`, `retry_delay_seconds`, and `timeout_seconds`.

## External Services And Secrets

- Treat configured Docker/PostgreSQL services as external infrastructure. Do not stop, remove, recreate, rename, reconfigure, or change ports, volumes, credentials, schemas, or environment unless explicitly asked.
- Keep machine-specific defaults in local HWE config, not in tracked source, generated projects, or this skill.
- Do not print secret values. Use environment variable names or redacted examples.
- Hosted AI provider secrets should be referenced by `api_key_env`, not stored in tracked files.

## Local API/UI

Start the API from the HWE repository root or set `HWE_CONFIG` explicitly:

```bash
cd "$HWE_REPO"
HWE_CONFIG="$HWE_CONFIG" "$HWE" serve --host "${HWE_API_HOST:-127.0.0.1}" --port "${HWE_API_PORT:-8711}"
npm --prefix ui run dev -- --host "${HWE_UI_HOST:-127.0.0.1}" --port "${HWE_UI_PORT:-5173}"
```

After changing `hwe.config.yaml` or workflow templates, restart the API. The Vite UI usually needs restart only for frontend/dependency changes.

Stop only known local console ports:

```bash
lsof -ti tcp:${HWE_API_PORT:-8711} 2>/dev/null | xargs -r kill
lsof -ti tcp:${HWE_UI_PORT:-5173} 2>/dev/null | xargs -r kill
```

## Profile Preflight Notes

HWE runtime handles profile preflight for agent tasks: `switch_commands`, optional healthcheck retries, then Hermes invocation as `chat -p <hermes_profile> -Q --source workflow-engine -q <prompt>` unless the configured command is already a profile wrapper.

Model switching belongs in HWE profile config, not generated projects or prompts. `switch_commands` are best-effort by default; use required switches only when a failed switch must block. Configure observed successful non-zero exits with `success_exit_codes`.

Hermes hook prompts are not HWE human actions. For trusted local profiles, use Hermes `hooks_auto_accept: true` or HWE `hermes_args: [--accept-hooks]`; do not use `--yolo` for routine HWE runs.
