-- Hermes Workflow Engine V2 schema
-- SQLite-compatible install schema.
-- Install with: sqlite3 .engine/engine.db < schema/engine_v2_schema.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    repo_path TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    default_branch TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_settings (
    project_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (project_id, key),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS project_policies (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '0.1.0',
    enabled INTEGER NOT NULL DEFAULT 1,
    body_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS environment_resources (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    locator TEXT,
    allowed_actions_json TEXT NOT NULL DEFAULT '[]',
    constraints_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workitem_id TEXT,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    profile TEXT,
    body TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workitems (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    conversation_id TEXT,
    title TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'feature',
    status TEXT NOT NULL DEFAULT 'draft',
    priority INTEGER NOT NULL DEFAULT 100,
    risk_level TEXT NOT NULL DEFAULT 'medium',
    requirements_md TEXT NOT NULL DEFAULT '',
    constraints_md TEXT NOT NULL DEFAULT '',
    current_workflow_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    accepted_at TEXT,
    cancelled_at TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS acceptance_criteria (
    id TEXT PRIMARY KEY,
    workitem_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    statement TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (workitem_id) REFERENCES workitems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workflows_v2 (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workitem_id TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '0.1.0',
    status TEXT NOT NULL DEFAULT 'created',
    planner_profile TEXT,
    strategy_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (workitem_id) REFERENCES workitems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    workitem_id TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    profile TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 100,
    risk_level TEXT NOT NULL DEFAULT 'medium',
    prompt_path TEXT,
    prompt_text TEXT,
    context_contract_json TEXT NOT NULL DEFAULT '{}',
    outputs_json TEXT NOT NULL DEFAULT '[]',
    gates_json TEXT NOT NULL DEFAULT '[]',
    allowed_paths_json TEXT NOT NULL DEFAULT '[]',
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    created_by TEXT,
    created_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ready_at TEXT,
    completed_at TEXT,
    FOREIGN KEY (workflow_id) REFERENCES workflows_v2(id) ON DELETE CASCADE,
    FOREIGN KEY (workitem_id) REFERENCES workitems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id TEXT NOT NULL,
    depends_on_task_id TEXT NOT NULL,
    dependency_policy TEXT NOT NULL DEFAULT 'succeeded',
    created_at TEXT NOT NULL,
    PRIMARY KEY (task_id, depends_on_task_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_locks (
    task_id TEXT NOT NULL,
    lock_name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'exclusive',
    created_at TEXT NOT NULL,
    PRIMARY KEY (task_id, lock_name),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS worker_claims (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    profile TEXT,
    status TEXT NOT NULL DEFAULT 'claimed',
    claimed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_runs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    workitem_id TEXT NOT NULL,
    claim_id TEXT,
    attempt INTEGER NOT NULL,
    profile TEXT,
    status TEXT NOT NULL DEFAULT 'started',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    exit_code INTEGER,
    result_json TEXT NOT NULL DEFAULT '{}',
    stdout_path TEXT,
    stderr_path TEXT,
    prompt_path TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (workflow_id) REFERENCES workflows_v2(id) ON DELETE CASCADE,
    FOREIGN KEY (workitem_id) REFERENCES workitems(id) ON DELETE CASCADE,
    FOREIGN KEY (claim_id) REFERENCES worker_claims(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS context_bundles_v2 (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    path TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    token_estimate INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES task_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS artifacts_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    sha256 TEXT,
    diff_path TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES task_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS gate_results_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    run_id TEXT,
    workitem_id TEXT,
    gate TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'task',
    status TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    findings_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES task_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (workitem_id) REFERENCES workitems(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planner_decisions (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    workitem_id TEXT NOT NULL,
    source_task_id TEXT,
    source_run_id TEXT,
    decision_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    created_tasks_json TEXT NOT NULL DEFAULT '[]',
    cancelled_tasks_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (workflow_id) REFERENCES workflows_v2(id) ON DELETE CASCADE,
    FOREIGN KEY (workitem_id) REFERENCES workitems(id) ON DELETE CASCADE,
    FOREIGN KEY (source_task_id) REFERENCES tasks(id) ON DELETE SET NULL,
    FOREIGN KEY (source_run_id) REFERENCES task_runs(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS human_actions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workitem_id TEXT,
    workflow_id TEXT,
    task_id TEXT,
    run_id TEXT,
    conversation_id TEXT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    questions_json TEXT NOT NULL DEFAULT '[]',
    options_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    response_json TEXT,
    requested_by TEXT,
    resolved_by TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    expires_at TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (workitem_id) REFERENCES workitems(id) ON DELETE CASCADE,
    FOREIGN KEY (workflow_id) REFERENCES workflows_v2(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL,
    FOREIGN KEY (run_id) REFERENCES task_runs(id) ON DELETE SET NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS git_checkpoints (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workitem_id TEXT,
    workflow_id TEXT,
    kind TEXT NOT NULL,
    tag_name TEXT,
    commit_sha TEXT,
    dirty_status TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (workitem_id) REFERENCES workitems(id) ON DELETE CASCADE,
    FOREIGN KEY (workflow_id) REFERENCES workflows_v2(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT,
    workitem_id TEXT,
    workflow_id TEXT,
    task_id TEXT,
    run_id TEXT,
    human_action_id TEXT,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (workitem_id) REFERENCES workitems(id) ON DELETE CASCADE,
    FOREIGN KEY (workflow_id) REFERENCES workflows_v2(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES task_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (human_action_id) REFERENCES human_actions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id, status);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON conversation_messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_workitems_project_status ON workitems(project_id, status, priority);
CREATE INDEX IF NOT EXISTS idx_acceptance_workitem ON acceptance_criteria(workitem_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_workflows_workitem ON workflows_v2(workitem_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_workflow_status ON tasks(workflow_id, status, priority);
CREATE INDEX IF NOT EXISTS idx_tasks_workitem_status ON tasks(workitem_id, status);
CREATE INDEX IF NOT EXISTS idx_task_deps_depends ON task_dependencies(depends_on_task_id);
CREATE INDEX IF NOT EXISTS idx_claims_task_status ON worker_claims(task_id, status, expires_at);
CREATE INDEX IF NOT EXISTS idx_runs_task_attempt ON task_runs(task_id, attempt);
CREATE INDEX IF NOT EXISTS idx_human_actions_pending ON human_actions(project_id, status, kind);
CREATE INDEX IF NOT EXISTS idx_decisions_workflow ON planner_decisions(workflow_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_v2_lookup ON events_v2(project_id, workitem_id, workflow_id, task_id, created_at);