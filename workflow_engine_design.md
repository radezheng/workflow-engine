# Hermes Workflow Engine Design

## 1. Purpose

Build a flexible workflow engine for Hermes-based agent work. The engine replaces Kanban as the workflow authority. Kanban can remain a historical experiment, but the new engine owns scheduling, context assembly, worker execution, validation gates, retries, and visualization.

Hermes profiles remain useful as worker runtimes:

- `default` for planning, orchestration artifacts, lightweight verification, and git lifecycle.
- `coder` for implementation and focused fixes.
- `reviewer` for semantic review.

The engine should not require every task to follow the same shape. Some steps are long, some are short, some run in parallel, some include inline review, and some expand review into a separate visible step.

## 2. Design Goals

- Support flexible step graphs rather than fixed coder-review chains.
- Support resource-aware concurrency with locks such as `repo`, `database`, `frontend`, `backend`, or custom paths.
- Treat context as a first-class input contract for every step.
- Run Hermes profile workers as bounded subprocess activities.
- Keep model switching inside the worker adapter preflight, not as noisy workflow nodes.
- Make validators deterministic and enforceable, not just reviewer prompt text.
- Provide a visual UI for graph state, nested step internals, logs, context bundles, artifacts, and gate failures.
- Preserve full auditability: what ran, with which context, under which policy version, and what changed.
- Allow later migration to Temporal, Prefect, or another durable backend without changing the domain workflow spec.

## 3. Non-Goals

- Do not reimplement Hermes chat, profile loading, or skill execution.
- Do not depend on Kanban for state transitions.
- Do not make every low-level action a workflow node.
- Do not use LLM review as the only approval gate for high-risk changes.
- Do not make context discovery an unbounded worker responsibility.
- Do not expose secrets in prompts, logs, context bundles, or UI.

## 4. Core Abstractions

### 4.1 Workflow

A workflow is a project-level state machine backed by a step graph.

```yaml
workflow:
  id: economic-cycle-dashboard
  version: 0.1.0
  workspace: /path/to/hermes-workspace
  concurrency:
    default: 2
    locks:
      repo: 1
      database: 1
      frontend: 1
      backend: 1
```

### 4.2 Step

A step is the unit of scheduling and visualization. It can contain several internal activities, such as model preflight, Hermes worker run, validation, inline review, and artifact snapshot.

```yaml
steps:
  - id: slice_1_data_ingestion
    title: Implement data ingestion safety slice
    kind: agent
    profile: coder
    needs: [planning_approved]
    locks: [repo, database]
    prompt: prompts/slice_1_data_ingestion.md
    outputs:
      - scripts/fetch_indicators.py
      - db/schema.sql
    context:
      profile: coder_data_task
      include:
        - requirements.sections: [data, external_services]
        - design.sections: [data_ingestion, database_ownership]
        - artifacts.paths:
            - scripts/fetch_indicators.py
        - skills.refs:
            - bridgewater-long-debt-cycle
            - mx-search
        - policies:
            - external_service_safety
            - data_provenance
    review:
      mode: separate_step
      reviewer: reviewer
      gates:
        - no_hardcoded_credentials
        - no_placeholder_ingestion
        - source_evidence_required
    on_fail:
      strategy: fix_then_review
      max_attempts: 2
```

### 4.3 Internal Activity

Internal activities are visible inside a step but do not clutter the top-level graph.

Typical activities:

- `compile_context`
- `switch_model`
- `healthcheck_model`
- `run_hermes_worker`
- `snapshot_artifacts`
- `run_validators`
- `run_inline_review`
- `parse_review_result`
- `decide_transition`

Only semantically meaningful steps appear on the graph by default. The UI can expand a step to show internal activities.

### 4.4 Context Bundle

A context bundle is the exact input package supplied to a Hermes worker. It is compiled before execution, stored, hashed, and linked to the run.

```json
{
  "id": "ctx_slice_1_data_ingestion_003",
  "step_id": "slice_1_data_ingestion",
  "token_estimate": 10420,
  "sources": [
    {"type": "file", "path": "docs/requirements.md", "section": "data", "sha256": "..."},
    {"type": "file", "path": "docs/design.md", "section": "database_ownership", "sha256": "..."},
    {"type": "skill", "name": "bridgewater-long-debt-cycle", "version": "..."},
    {"type": "policy", "name": "external_service_safety", "version": "0.1.0"}
  ],
  "excluded": ["secrets", "old_board_logs", "unrelated_frontend_docs"],
  "freshness": "latest"
}
```

### 4.5 Gate

A gate is a deterministic or semi-deterministic validation unit. Review text can inform a gate, but high-risk gates must have deterministic checks where possible.

Examples:

- `no_hardcoded_credentials`
- `no_external_service_mutation`
- `no_placeholder_ingestion`
- `source_evidence_required`
- `python_syntax_ok`
- `frontend_build_ok`
- `api_contract_tests_ok`

### 4.6 Policy

Policies are reusable safety and workflow rules included in context bundles and enforced by validators.

Examples:

- External Docker/PostgreSQL safety.
- Credential handling.
- Source data provenance.
- Review result parsing.
- Git lifecycle.
- Context budget and redaction.

## 5. Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                     Web UI                              │
│  graph, step detail, logs, context, artifacts, gates     │
└───────────────────────▲─────────────────────────────────┘
                        │ HTTP/WebSocket
┌───────────────────────┴─────────────────────────────────┐
│                  Engine API                              │
│  workflow CRUD, run control, event stream, artifact API  │
└───────────────────────▲─────────────────────────────────┘
                        │
┌───────────────────────┴─────────────────────────────────┐
│               Workflow Runtime                           │
│  scheduler, lock manager, transition engine, retries     │
└───────▲───────────────▲───────────────▲─────────────────┘
        │               │               │
┌───────┴──────┐ ┌──────┴──────┐ ┌──────┴────────────────┐
│ Context      │ │ Worker      │ │ Validation             │
│ Compiler     │ │ Adapter     │ │ Engine                 │
└───────▲──────┘ └──────▲──────┘ └──────▲────────────────┘
        │               │               │
┌───────┴───────────────┴───────────────┴────────────────┐
│                   Storage                                │
│  SQLite/Postgres: workflows, runs, events, locks, gates  │
│  Filesystem: context bundles, logs, artifacts, snapshots │
└─────────────────────────────────────────────────────────┘
```

## 6. Runtime Responsibilities

### 6.1 Scheduler

The scheduler chooses ready steps whose dependencies are satisfied and whose locks are available.

Readiness requires:

- All `needs` dependencies are in an approved or completed state required by the edge policy.
- Context sources are resolvable.
- Required locks can be acquired.
- The step has not exceeded retry policy.
- Any human approval requirement is satisfied.

### 6.2 Lock Manager

Locks avoid unsafe parallelism without forcing global serial execution.

Lock examples:

```yaml
locks:
  - repo
  - database
  - path:scripts/fetch_indicators.py
  - service:external-postgres:read_only
```

Rules:

- `repo` serializes broad repository writes.
- `path:<file>` serializes focused edits to one artifact.
- `database` serializes schema/data mutation.
- `service:<name>:read_only` may run in parallel with other read-only locks.
- `service:<name>:mutate` conflicts with all locks for that service and may require human approval.

### 6.3 Worker Adapter

The worker adapter runs Hermes profiles and hides low-level mechanics from workflow definitions.

Input:

```json
{
  "profile": "coder",
  "workspace": "/path/to/project",
  "prompt": "...",
  "context_bundle_path": ".engine/context/ctx_123.md",
  "timeout_seconds": 3600
}
```

Adapter behavior:

1. Load the profile config.
2. Run model switch command if configured.
3. Run model health check.
4. Build the final prompt from task prompt plus context bundle.
5. Run `hermes -p <profile> chat -q <prompt>` in the workspace.
6. Capture stdout, stderr, exit code, runtime, and process metadata.
7. Snapshot declared artifacts and git diff.
8. Return a normalized worker result.

Model switch remains a preflight inside `run_worker_task`, not a top-level workflow node.

### 6.4 Context Compiler

The context compiler resolves each step's context contract into a concrete bundle.

Responsibilities:

- Resolve files, sections, skills, policies, previous results, and artifact diffs.
- Redact secrets and excluded paths.
- Check freshness via hashes and timestamps.
- Summarize only when a source exceeds budget.
- Store source metadata and bundle hash.
- Fail the step before worker launch if mandatory context is missing.

Workers may request more context by returning a structured block:

```json
{
  "status": "blocked",
  "needs_context": [
    {
      "type": "file",
      "path": "docs/source_strategy.md",
      "reason": "Need exact mx-search extraction rules"
    }
  ]
}
```

The engine decides whether to provide more context, create a planning fix step, or escalate to the user.

### 6.5 Validation Engine

The validation engine runs gates after worker execution and after review when configured.

Gate result shape:

```json
{
  "gate": "no_hardcoded_credentials",
  "status": "failed",
  "severity": "blocker",
  "findings": [
    {
      "path": "scripts/fetch_indicators.py",
      "message": "DB_USER defaults to external service identity hindsight_user"
    }
  ]
}
```

Gate statuses:

- `passed`
- `failed`
- `warning`
- `skipped`
- `blocked_missing_context`

Only `passed` and allowed `warning` states can advance an approval edge.

## 7. Review Modes

### 7.1 None

Used for mechanical or low-risk steps.

```yaml
review:
  mode: none
```

### 7.2 Inline

The top-level graph shows one step. Internally it runs worker, validators, reviewer, and final gates.

```yaml
review:
  mode: inline
  reviewer: reviewer
  gates:
    - api_contract_tests_ok
```

Best for moderate-risk steps where separate review visualization would add noise.

### 7.3 Separate Step

The engine creates or uses an explicit review step in the graph.

```yaml
review:
  mode: separate_step
  reviewer: reviewer
  gates:
    - no_hardcoded_credentials
    - no_placeholder_ingestion
```

Best for high-risk changes: database, security, data ingestion, external services, release, or large UI/contract changes.

### 7.4 Human Approval

Human approval can be added as a gate, not as a replacement for automated validation.

```yaml
review:
  mode: separate_step
  require_human_approval: true
```

## 8. State Model

Step states:

- `pending`
- `ready`
- `context_compiling`
- `running`
- `validating`
- `reviewing`
- `approved`
- `completed`
- `needs_change`
- `blocked`
- `failed`
- `canceled`

Run states:

- `queued`
- `started`
- `succeeded`
- `failed`
- `timed_out`
- `canceled`

Approval transitions:

- `completed` is not the same as `approved`.
- A code-producing step can complete but still fail validation.
- A reviewer can approve semantically, but hard gates can still force `needs_change`.
- Downstream approval edges require both acceptable review result and passing gates.

## 9. Data Storage

Start with SQLite for local MVP. Keep a repository-compatible abstraction so Postgres can be used later.

Tables:

- `workflows(id, version, workspace, status, created_at, updated_at)`
- `steps(id, workflow_id, title, kind, profile, state, attempt, spec_json)`
- `edges(workflow_id, from_step, to_step, edge_policy)`
- `locks(name, holder_step_id, holder_run_id, acquired_at, expires_at)`
- `runs(id, step_id, attempt, status, started_at, ended_at, exit_code)`
- `events(id, workflow_id, step_id, run_id, type, payload_json, created_at)`
- `context_bundles(id, step_id, run_id, path, manifest_json, sha256, created_at)`
- `artifacts(id, step_id, run_id, path, kind, sha256, diff_path, created_at)`
- `gate_results(id, step_id, run_id, gate, status, severity, findings_json)`
- `approvals(id, step_id, run_id, approver, status, note, created_at)`

Filesystem layout:

```text
.engine/
  runs/<run-id>/
    stdout.log
    stderr.log
    prompt.md
    result.json
    diff.patch
  context/<context-id>.md
  context/<context-id>.json
  artifacts/<run-id>/...
```

## 10. Workflow Spec Example

```yaml
workflow:
  id: hermes-agent-project
  workspace: /path/to/hermes-workspace
  project: example-project
  concurrency:
    default: 2
    locks:
      repo: 1
      database: 1

profiles:
  default:
    hermes_profile: default
    hermes_command: hermes
    healthcheck:
      url: http://localhost:1234/v1/chat/completions
      model: planner-model
  coder:
    hermes_profile: coder
    hermes_command: hermes
    healthcheck:
      url: http://localhost:1234/v1/chat/completions
      model: coder-model
  reviewer:
    hermes_profile: reviewer
    hermes_command: hermes
    healthcheck:
      url: http://localhost:1234/v1/chat/completions
      model: reviewer-model

context_profiles:
  planning:
    token_budget: 30000
    include: [user_request, policies, skills]
  coder_small_fix:
    token_budget: 8000
    include: [failed_gates, exact_files, design_excerpt, policies]
  reviewer:
    token_budget: 12000
    include: [task_spec, changed_diff, acceptance_criteria, validator_results, policies]

steps:
  - id: init_repo
    title: Initialize repository
    kind: command
    locks: [repo]
    commands:
      - git init
      - git status --short
    gates:
      - git_initialized

  - id: plan
    title: Produce requirements and design
    kind: agent
    profile: default
    needs: [init_repo]
    locks: [repo]
    prompt: prompts/plan.md
    context:
      profile: planning
    outputs:
      - docs/requirements.md
      - docs/design.md
    review:
      mode: inline
      reviewer: reviewer
      gates:
        - planning_docs_complete
        - external_services_declared

  - id: data_slice
    title: Implement data ingestion slice
    kind: agent
    profile: coder
    needs: [plan]
    locks: [repo, database]
    prompt: prompts/data_slice.md
    context:
      profile: coder_data_task
    outputs:
      - scripts/fetch_indicators.py
    review:
      mode: separate_step
      reviewer: reviewer
      gates:
        - no_hardcoded_credentials
        - no_external_service_mutation
        - no_placeholder_ingestion
        - source_evidence_required
    on_fail:
      strategy: fix_then_review
      max_attempts: 2
```

## 11. Validators

Validators are plugins with a stable interface.

```python
class GateResult(TypedDict):
    gate: str
    status: Literal["passed", "failed", "warning", "skipped", "blocked_missing_context"]
    severity: Literal["info", "warning", "blocker"]
    findings: list[dict]


def validate(workspace: Path, step: StepSpec, run: RunRecord) -> GateResult:
    ...
```

Initial validators:

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

Example hard-coded credential validator checks:

- Forbidden literal password assignments.
- `DB_PASSWORD` default value other than empty/required.
- `DB_USER` defaulting to external-service usernames such as `hindsight_user`.
- `docker inspect` or container environment scraping used for project credentials.

## 12. UI Design

The UI should feel like an execution cockpit, not a marketing dashboard.

Primary views:

- Workflow graph with collapsible steps.
- Run timeline with event stream.
- Step detail panel.
- Context bundle viewer.
- Artifact and diff viewer.
- Gate results panel.
- Worker log viewer.
- Retry/fix chain viewer.

Graph behavior:

- Show top-level steps by default.
- Expand a step to show internal activities.
- Color state by status: pending, running, validating, approved, needs change, blocked, failed.
- Show locks held by a running step.
- Show gate failures as badges.

Step detail tabs:

- `Overview`: objective, state, attempts, locks, profile.
- `Context`: included sources, excluded sources, hashes, token estimate.
- `Prompt`: final prompt sent to Hermes.
- `Logs`: stdout, stderr, structured events.
- `Artifacts`: changed files, snapshots, diffs.
- `Gates`: validator results and findings.
- `Review`: reviewer output and parsed decision.

Actions:

- Start workflow.
- Pause scheduling.
- Cancel running step.
- Retry failed step.
- Approve human gate.
- Provide requested context.
- Export run bundle.

## 13. API Sketch

```http
POST /workflows
GET /workflows/{id}
POST /workflows/{id}/start
POST /workflows/{id}/pause
POST /workflows/{id}/resume
POST /steps/{id}/retry
POST /steps/{id}/cancel
GET /workflows/{id}/events
GET /steps/{id}/context
GET /steps/{id}/logs
GET /steps/{id}/artifacts
GET /steps/{id}/gates
POST /steps/{id}/approvals
```

## 14. MVP Plan

### Slice 1: Local Engine CLI

- Parse `workflow.yaml`.
- Store workflow and step state in SQLite.
- Run command steps and Hermes agent steps serially.
- Implement model switch and healthcheck inside worker adapter.
- Compile basic context bundles from files and policies.
- Capture logs and artifact diffs.
- Run basic validators.

### Slice 2: Resource Locks and Parallelism

- Add lock manager.
- Support `needs` dependencies.
- Allow parallel execution when locks do not conflict.
- Add step timeout and cancellation.

### Slice 3: Review Modes and Retry Strategy

- Implement inline review.
- Implement separate review step expansion.
- Implement `fix_then_review` retry strategy.
- Parse reviewer conclusions but keep hard validators authoritative.

### Slice 4: Web UI

- FastAPI backend over SQLite.
- React/Vite frontend.
- Graph view, step detail panel, logs, context, gates.
- WebSocket or polling event stream.

### Slice 5: Context Compiler V2

- Section extraction.
- Skill reference loading.
- Token budget estimation.
- Summarization with source manifests.
- Context request flow for blocked workers.

### Slice 6: Durable Backend Option

- Evaluate whether to keep local engine or use Temporal/Prefect underneath.
- Preserve the same workflow spec and domain API.
- Map top-level steps to durable activities only if needed.

## 15. Open Questions

- Should the first implementation use SQLite only, or start with Postgres because the UI and event stream will grow quickly?
- Should Hermes workers run through subprocess only, or should there be a future stable Hermes API adapter?
- How strict should sandboxing be for generated project edits?
- Should context bundles be stored inside each project repo or in a global engine workspace?
- Should the UI allow editing workflow specs, or should YAML remain source-controlled and read-only in the UI for MVP?

## 16. Lessons Incorporated From Kanban Dogfood

- Empty task bodies must be impossible, not merely discouraged.
- Review checks added after dispatch do not protect the run.
- Reviewer text cannot be the only gate; deterministic validators must block obvious failures.
- Model switching has to happen before worker launch.
- Context must be compiled, visible, and versioned.
- Workers should not own global topology.
- Fix/retry chains should be created by the engine, not by an agent guessing Kanban commands.
- Resource locks are better than forcing all work through `max 1`.
- The UI should show what context the model actually received, not what humans assumed it had.