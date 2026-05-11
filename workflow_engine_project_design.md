# Hermes Workflow Engine Project Design

Date: 2026-05-11
Status: Draft

## 1. Purpose

HWE started as a mostly static workflow graph. Project workflow mode turns it into a project-level work management system for Hermes profiles.

The goal is:

> A human describes a new or changed requirement. The system clarifies missing information when needed, creates a project work item, lets a planner design and decompose the work, dispatches focused tasks to worker profiles, dynamically creates follow-up tasks from evidence, waits for human approval at risk points, validates the result, and closes the work item with audit records and recovery checkpoints.

HWE should still support static YAML workflows, but the primary project model becomes project plus work items plus a dynamic task queue.

## 2. Design Goals

- Track work by project, not only by workflow file.
- Treat `WorkItem` as the user-facing unit of delivery.
- Treat `Task` as the worker-facing unit of execution.
- Support both new-project work and modification requests against existing projects.
- Let planner profiles clarify requirements before execution.
- Manage reusable role prompt templates so reviewer, planner, coder, and QA best practices can accumulate per project.
- Let workers report missing information during execution without pretending the task is complete.
- Let each task explicitly declare the skills it expects the worker to load or follow.
- Allow human approval gates for risky or irreversible actions.
- Let planner profiles dynamically create, cancel, or revise tasks based on run results and gate failures.
- Keep context bundles, prompts, logs, diffs, artifacts, decisions, approvals, and gate results auditable.
- Keep one `.engine/` per project so projects can be tracked and recovered independently.
- Store the project database schema separately so another machine can install or migrate the engine state format.

## 3. Non-Goals

- Do not make the worker profile own product decisions.
- Do not let coder workers freely expand scope without a planner decision.
- Do not require every workflow to be fully known before execution begins.
- Do not use LLM review as the only gate for high-risk changes.
- Do not expose secrets in context bundles, prompts, logs, or UI.
- Do not block all work on human approval. Approval is required only where policy or risk says it is required.

## 4. Core Concepts

### 4.1 Project

A project is a real workspace folder with its own `.engine/` directory. It owns work items, conversations, policies, task queues, model profile configuration, environment constraints, and recovery checkpoints.

Example:

```text
<configured-workspace-root>/todo-app/.engine/
```

### 4.2 Conversation

A conversation records the human request and any clarification exchange before or during execution.

The conversation is not just chat history. It is the source of decisions and requirement changes.

Typical message kinds:

- Human request.
- Planner clarification question.
- Human answer.
- Planner summary of accepted requirements.
- Human change request during execution.
- Approval request and response.

### 4.3 WorkItem

A work item is the user-facing unit of delivery.

Examples:

- Add notes with Markdown support to the Todo app.
- Fix backend import errors.
- Create a new FastAPI project.
- Refactor data ingestion without changing public APIs.

Suggested fields:

```text
workitem_id
project_id
title
type: feature | bugfix | refactor | research | maintenance
status: draft | clarifying | ready | planning | executing | validating | waiting_for_human | accepted | blocked | cancelled | superseded
priority
risk_level
requirements_md
constraints_md
acceptance_criteria
current_workflow_id
created_from_conversation_id
```

### 4.4 Workflow

A workflow is the planner's current execution strategy for a work item. It may start partial and grow dynamically.

Static YAML workflows remain useful as an import/export format, but project workflow mode should persist workflows and tasks in the project database.

### 4.5 Task

A task is the worker-facing unit of execution. Workers should receive narrow tasks with explicit scope, outputs, gates, and allowed files.

Suggested fields:

```text
task_id
workflow_id
workitem_id
title
kind: intake | design | code | test | review | command | acceptance | approval | info_request
profile: planner | coder | reviewer | qa | command
status: pending | ready | claimed | running | waiting_for_info | waiting_for_approval | validating | succeeded | failed | stale | cancelled
dependencies
locks
context_contract
skills
prompt_template_id
prompt
outputs
gates
attempt
max_attempts
claim_owner
claim_expires_at
```

### 4.6 Planner

The planner is responsible for product and workflow decisions:

- Convert conversation into a work item.
- Ask clarifying questions when requirements are incomplete.
- Produce requirements, design, risk assessment, acceptance criteria, and initial task graph.
- Observe task results and gate failures.
- Create follow-up tasks.
- Decide whether the work item is ready for final acceptance.

The planner can be a Hermes `reviewer` profile backed by Gemma or another local model.

### 4.7 Role Prompt Template

A role prompt template is a reusable project-scoped instruction block for a worker role.

Examples:

- Reviewer implementation review checklist.
- Planner decomposition best practices.
- QA acceptance criteria verification template.
- Coder constraints for small-slice implementation.

Templates should be versioned by `role`, `name`, and `version`. A task may reference a template by id and may still include task-specific prompt text. This lets the project accumulate stable role guidance without copying the same best-practice text into every task.

HWE keeps prompt template source files in its own configured template root, defaulting to `./ptemplate` relative to `hwe.config.yaml`. This is the workflow-engine operator's template library, not a path inside the target project. Creating a project role template can read `<prompt_template_root>/<role>/<name>.md` and store that content in the project's `.engine` database.

### 4.8 Worker

Workers execute tasks from the queue. They should not make broad product decisions.

Examples:

- `coder`: implementation and focused fixes.
- `reviewer`: semantic QA and acceptance review.
- `command`: deterministic shell tasks.

Workers may report missing information or request approval, but they should not silently invent missing requirements.

### 4.9 Human Action

Some tasks need a human before continuing. HWE should model these explicitly.

Two primary human action kinds:

- `info_request`: the system needs an answer to proceed.
- `approval_request`: the system needs permission to take or accept an action.

Examples:

- Missing info: `Should notes support sharing?`
- Approval: `This task will run a database migration against the project dev DB. Approve?`
- Approval: `Planner wants to expand scope by adding full-text search. Approve as same work item or create a new work item?`

## 5. Lifecycle

### 5.1 Intake

Input can be casual:

```text
Add a left menu and notes with Markdown support.
```

Planner inspects the project and decides one of:

- `ready_to_plan`: enough information is available.
- `needs_clarification`: ask bounded questions.
- `blocked`: cannot proceed because required project or environment information is missing.

Clarification should be limited. A good default is at most 3 to 5 questions per turn.

### 5.2 WorkItem Creation

Before execution, the planner writes a compact work item spec:

```markdown
## Requirement
...

## Acceptance Criteria
- User can create, edit, delete, and view notes.
- Notes support Markdown editing and preview.
- Existing Todo behavior still works.

## Constraints
- Use the existing project structure.
- Do not hard-code database credentials.
- Do not modify the existing Docker PostgreSQL container configuration.
```

### 5.3 Planning and Design

Planner creates or updates:

- Requirements document.
- Design document.
- Risk assessment.
- Initial task graph.
- Validation plan.
- Human approval points.

The planner does not need to create every future task immediately. It can create the first safe batch and use later observations to extend the queue.

### 5.4 Dispatch and Claim

The task queue marks a task `ready` when:

- Dependencies are satisfied.
- Required locks are available.
- Required information is present.
- Required approval is granted.
- Retry budget remains.
- A capable profile is available.

Workers claim tasks with a lease. If the worker disappears or the lease expires, the task becomes `stale` and can be retried or escalated to planner.

### 5.5 Execution

For every task run, HWE stores:

- Worker profile and model switch details.
- Final prompt.
- Context bundle manifest and hash.
- Logs.
- Exit code.
- Declared artifact snapshots.
- Git diff.
- Gate results.

### 5.6 Missing Information During Execution

A worker may discover that the task cannot be completed safely because information is missing.

The worker should emit a structured result instead of guessing:

```json
{
  "status": "needs_info",
  "questions": [
    {
      "id": "q1",
      "question": "Should notes be private to the local browser session or stored in PostgreSQL?",
      "reason": "Persistence target affects backend and database schema.",
      "options": ["PostgreSQL", "Local browser only"]
    }
  ]
}
```

Runtime behavior:

1. Mark task as `waiting_for_info`.
2. Create a `human_actions` row with `kind=info_request`.
3. Notify the user through CLI/UI/chat.
4. Store the human answer in the conversation.
5. Wake planner to decide whether to resume the same task, revise it, or create new tasks.

### 5.7 Human Approval During Execution

Approval is required when policy or risk says the system must not proceed automatically.

Examples:

- Mutating a shared database.
- Running a destructive shell command.
- Changing credentials, auth, billing, deployment, or cloud resources.
- Expanding scope beyond accepted requirements.
- Accepting a high-risk final result with known test gaps.

Approval request shape:

```json
{
  "kind": "approval_request",
  "title": "Approve database migration",
  "risk_level": "medium",
  "requested_action": "Run backend/init_db.sql against todo_app_dev",
  "evidence": ["docs/design_notes.md", "backend/init_db.sql"],
  "options": ["approve", "reject", "request_changes"]
}
```

Runtime behavior:

1. Mark task or workflow `waiting_for_approval`.
2. Stop dispatching dependent tasks.
3. Record approval request with evidence.
4. Resume only after an explicit decision.
5. If rejected, planner creates a revision task or marks the work item blocked.

### 5.8 Planner Observation and Dynamic Task Creation

Planner should observe at key points, not after every tiny action.

Recommended triggers:

- Initial planning complete.
- Important design or implementation task succeeded.
- Any task failed.
- Any deterministic gate failed.
- Worker requested missing information.
- Worker requested approval.
- Task queue is empty but acceptance criteria are not all satisfied.
- User submits a change request.

Planner output should be structured as a decision:

```json
{
  "decision": "create_followup_tasks",
  "reason": "Notes UI creates blank notes but backend rejects empty content with 422.",
  "tasks": [
    {
      "title": "Allow blank note content on create",
      "profile": "coder",
      "outputs": ["backend/main.py"],
      "gates": ["python_syntax_ok"]
    },
    {
      "title": "Verify note creation from UI",
      "profile": "reviewer",
      "gates": ["browser_smoke_ok"]
    }
  ]
}
```

Every planner decision is stored in `planner_decisions` for auditability.

### 5.9 Validation and Acceptance

Validation is layered.

Task-level gates:

- Syntax checks.
- Unit tests.
- Build checks.
- Declared artifact existence.
- No hardcoded credentials.

Workitem-level gates:

- Acceptance criteria satisfied.
- Integration smoke passed.
- Regression checks passed.
- Required docs updated.

Project-level gates:

- Git checkpoint start tag exists.
- Git completion tag exists.
- No unexpected untracked debug artifacts.
- Environment constraints were respected.

Only after final acceptance should the work item become `accepted`.

## 6. State Machines

### 6.1 WorkItem States

```text
draft
  -> clarifying
  -> ready
  -> planning
  -> executing
  -> validating
  -> accepted
```

Side states:

```text
waiting_for_human
blocked
cancelled
superseded
```

### 6.2 Task States

```text
pending
  -> ready
  -> claimed
  -> running
  -> validating
  -> succeeded
```

Failure and pause states:

```text
waiting_for_info
waiting_for_approval
failed
stale
retry_ready
cancelled
```

### 6.3 Human Action States

```text
pending
  -> answered | approved | rejected | request_changes | expired | cancelled
```

## 7. Git and Recovery Policy

Each work item should have recoverable boundaries.

Before work starts:

- Check whether repo is initialized.
- If new project, initialize git and create an initial commit.
- If existing project is dirty, record dirty baseline and ask approval before continuing.
- Create a start tag, for example `hwe/workitems/<workitem_id>/start`.

After acceptance:

- Ensure validation evidence is recorded.
- Create a completion tag, for example `hwe/workitems/<workitem_id>/complete`.
- Write final acceptance report.

On failure:

- Preserve logs, context bundles, diffs, and partial artifacts.
- Do not reset automatically.
- Offer recovery options: retry task, create fix task, revert to start tag, or pause for human decision.

## 8. Queue and Locking

Locks prevent unsafe parallelism.

Recommended lock names:

```text
repo
path:<relative-path>
component:frontend
component:backend
database:<name>:read
database:<name>:mutate
service:<name>:read
service:<name>:mutate
```

Rules:

- `repo` serializes broad writes.
- `path:<file>` serializes edits to a file or directory.
- `database:*:mutate` conflicts with all read and mutate locks for the same database unless policy allows it.
- `service:*:mutate` requires explicit project policy and may require human approval.

## 9. CLI Sketch

Initial project workflow commands:

```bash
hwe project init /path/to/project
hwe project status

hwe workitem create --project todo-app --title "Add notes" --request request.md
hwe workitem list
hwe workitem show <workitem-id>

hwe intake "Add notes with markdown"
hwe human-action list <project> --status pending
hwe answer <project> <human-action-id> --text "Use PostgreSQL"
hwe approve <project> <human-action-id>
hwe reject <project> <human-action-id> --reason "Use isolated smoke DB instead"

hwe planner run <workitem-id>
hwe queue list
hwe run-workitem <project> <workitem-id> --dry-run --max-tasks 1
hwe worker run --profile coder
```

The first runnable path is push-style execution: `hwe run-workitem` claims ready tasks, records task runs, writes prompts/logs, and completes or fails tasks through the project queue. The schema still supports pull-style worker claims for future daemon workers.

Project workflow runners should use HWE-local profile preflight settings from `hwe.config.yaml`, such as `profiles.<name>.switch_command`, `healthcheck`, `hermes_command`, and `success_exit_codes`. These settings are machine/runtime concerns and must not be embedded in skills or generated target projects.

## 10. UI Sketch

The UI should show:

- Project list.
- Workitem board.
- Conversation and clarification panel.
- Task queue with status, profile, locks, and attempts.
- Workflow graph.
- Role prompt templates by role and version.
- Human actions waiting for answer or approval.
- Planner decisions.
- Logs, context bundles, artifacts, and diffs.
- Acceptance criteria checklist and evidence.

## 11. Database Schema

The installable SQLite schema is stored separately at:

- [schema/engine_schema.sql](schema/engine_schema.sql)

The schema intentionally uses SQLite-compatible types and JSON-as-text fields so it can be installed locally and later migrated to Postgres if needed.

Install example:

```bash
sqlite3 .engine/engine.db < schema/engine_schema.sql
```

The schema includes tables for:

- Projects and project policy.
- Role prompt templates.
- Conversations and messages.
- Work items and acceptance criteria.
- Workflows and tasks.
- Task skill requirements.
- Task dependencies and locks.
- Worker claims and runs.
- Context bundles, artifacts, gates, decisions, human actions, checkpoints, and events.

## 12. MVP Implementation Plan

### Phase 1: Persistent Project Work Items

- Add project schema migration or install path.
- Add `Project`, `Conversation`, `WorkItem`, and `AcceptanceCriteria` storage APIs.
- Add CLI commands to create/list/show work items.
- Bind existing workflow IDs to work items.

### Phase 2: Task Queue

- Add `Task`, dependencies, locks, and worker claims.
- Convert static workflow steps into queued tasks.
- Add `run-workitem` push-style execution for ready tasks.
- Add lease timeout and stale task recovery.

### Phase 3: Human Actions

- Add `info_request` and `approval_request` tasks/actions.
- Add CLI/UI answer and approval commands.
- Teach runtime to pause dependent tasks until action is resolved.

### Phase 4: Planner Observe

- Add planner decision schema and parser.
- Trigger planner on task failure, missing info, approval rejection, and empty queue.
- Let planner create follow-up tasks dynamically.

### Phase 5: Acceptance and Recovery

- Add workitem-level acceptance criteria gates.
- Add start and completion checkpoint tags.
- Add final report generation and close workflow.
- Add recovery commands for retry, pause, resume, and revert guidance.

API and UI should be built after the CLI runner is stable, using the same project storage and runtime surfaces rather than introducing a separate execution path.

## 13. Open Questions

- Should work item IDs be human-readable slugs, UUIDs, or both?
- Should planner-generated tasks be stored as prompt text, prompt files, or both?
- Should `.engine/engine.db` support automatic migrations, or should project workflow mode use a fresh database for now?
- What human approvals are mandatory by default versus configured per project?
- Should worker daemon mode be added now, or only after push-style project workflow execution works?

## 14. Summary

HWE should move from static workflow execution to dynamic project work management.

The central loop is:

```text
human request
  -> clarification when needed
  -> work item
  -> planner design and task decomposition
  -> task queue
  -> worker execution
  -> validation
  -> planner observation
  -> more tasks or final acceptance
  -> checkpoint and close
```

The important additions over the static workflow model are work items, conversations, task queue leases, missing-information pauses, human approval gates, planner decisions, and installable schema.