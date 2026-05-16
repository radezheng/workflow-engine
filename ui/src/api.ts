export type ProjectRecord = {
  id: string;
  name: string;
  root_path: string;
  status: string;
  updated_at: string;
  project_ref: string;
};

export type Workitem = {
  id: string;
  project_id: string;
  title: string;
  type: string;
  status: string;
  priority: number;
  risk_level: string;
  current_workflow_id: string | null;
  requirements_md: string;
  constraints_md: string;
  created_at: string;
  updated_at: string;
};

export type Workflow = {
  id: string;
  project_id: string;
  workitem_id: string;
  status: string;
  planner_profile: string | null;
  created_at: string;
  updated_at: string;
};

export type Task = {
  id: string;
  workflow_id: string;
  workitem_id: string;
  title: string;
  kind: string;
  profile: string | null;
  status: string;
  priority: number;
  risk_level: string;
  attempt: number;
  prompt_template_ref: string | null;
  prompt_text: string | null;
  outputs: string[];
  gates: string[];
  skills: string[];
  created_at: string;
  updated_at: string;
  workflow_actions?: {
    materialize_plan?: WorkflowAction;
  };
};

export type WorkflowAction = {
  workflow_template_id: string;
  profile?: string | null;
  prompt_template_ref?: string | null;
  parameters?: Record<string, string>;
};

export type WorkflowTemplate = {
  id: string;
  name: string;
  description?: string;
  version?: string | number;
  source: string;
  path: string;
  parameters: Record<string, { default?: string; description?: string } | string>;
  profiles: Record<string, string>;
  prompt_templates: Record<string, string>;
  planning_task: Record<string, unknown>;
  materialize?: Record<string, unknown>;
  child_workflows?: Array<Record<string, unknown>>;
  resolved_parameters?: Record<string, string>;
};

export type TaskRun = {
  id: string;
  task_id: string;
  workflow_id: string;
  status: string;
  exit_code: number | null;
  started_at: string;
  ended_at: string | null;
  stdout_path?: string | null;
  result: Record<string, unknown>;
};

export type RunStream = 'stdout' | 'stderr' | 'prompt';
export type RunView = RunStream | 'timeline';

export type RunLog = {
  run_id: string;
  stream: RunStream;
  path?: string;
  text: string;
};

export type RunTimelineToolCall = {
  id?: string | null;
  type?: string | null;
  name?: string | null;
  arguments: string;
};

export type RunTimelineEvent = {
  index: number;
  role: string;
  timestamp?: string | null;
  content: string;
  tool_call_id?: string | null;
  tool_calls: RunTimelineToolCall[];
  finish_reason?: string | null;
};

export type RunTimeline = {
  run_id: string;
  session_id: string | null;
  status: 'ok' | 'missing_session_id' | 'missing_session_log' | string;
  path?: string;
  searched_paths?: string[];
  session?: Record<string, unknown> | null;
  events: RunTimelineEvent[];
};

export type HumanAction = {
  id: string;
  kind: string;
  status: string;
  title: string;
  body: string;
  project_id?: string;
  workitem_id: string | null;
  workflow_id: string | null;
  task_id: string | null;
  run_id: string | null;
  questions: { id?: string; question?: string }[];
  options: string[];
  evidence: string[];
  requested_by: string | null;
  created_at: string;
  resolved_at?: string | null;
  resolved_by?: string | null;
  response?: Record<string, unknown> | null;
};

export type ConfigStatus = {
  path: string | null;
  exists: boolean;
  default_workspace_root: string | null;
  prompt_template_root: string | null;
  workflow_template_root: string | null;
  project_database: {
    backend: string;
    host?: string;
    port?: number;
    database?: string;
    user?: string;
    schema?: string;
    maxconn?: number;
    has_password?: boolean;
  };
  profiles: string[];
  ai_providers: string[];
};

export type PromptTemplate = {
  id: string;
  source: 'public' | 'project';
  role: string;
  name: string;
  version: string;
  description: string;
  body_md: string;
  tags: string[];
  path: string;
  updated_at: number;
};

export type ProjectEvent = {
  id: number;
  type: string;
  task_id: string | null;
  run_id: string | null;
  human_action_id: string | null;
  created_at: string;
  payload: Record<string, unknown>;
};

export type Dashboard = {
  project: ProjectRecord;
  workitem: Workitem;
  workflows: Workflow[];
  current_workflow: Workflow | null;
  tasks: Task[];
  runs: TaskRun[];
  human_actions: HumanAction[];
  events: ProjectEvent[];
};

export type RunSummary = {
  project_id: string;
  workitem_id: string;
  workflow_id: string;
  tasks_started: number;
  tasks_succeeded: number;
  tasks_failed: number;
  waiting_for_human: number;
  blocked: string[];
  failed: string[];
  open: string[];
};

export type RunRequest = {
  id: string;
  project_id: string;
  workitem_id: string;
  workflow_id: string;
  task_id: string | null;
  kind: string;
  status: string;
  requested_worker_id: string | null;
  worker_id: string | null;
  profile: string | null;
  max_tasks: number | null;
  dry_run: boolean;
  result: Record<string, unknown>;
  error: string | null;
  created_at: string;
  claimed_at: string | null;
  completed_at: string | null;
  updated_at: string;
};

export type CreateProjectInput = {
  name: string;
  project_ref?: string;
  project_id?: string;
};

export type CreateWorkitemInput = {
  title: string;
  type: string;
  requirements: string;
  constraints: string;
  acceptance: string[];
  priority: number;
  risk_level: string;
};

export type CreatePromptTemplateInput = {
  role: string;
  name: string;
  version: string;
  description: string;
  tags: string[];
  body?: string;
};

export type UpdateTaskInput = {
  project_id: string;
  profile?: string | null;
  prompt_template_ref?: string | null;
  prompt_text?: string | null;
};

export type TaskPromptPreview = {
  task_id: string;
  prompt_template_ref: string | null;
  text: string;
};

export type AIProvider = {
  name: string;
  type: string;
  base_url: string;
  model: string;
  has_api_key: boolean;
};

export type AIAssistTarget = 'project' | 'workitem' | 'human_action' | 'prompt_template';

export type AIAssistMessage = {
  role: 'user' | 'assistant';
  content: string;
};

export type AIAssistResponse = {
  message: string;
  draft: Record<string, unknown>;
  ready: boolean;
  raw: string;
};

export type AIAssistContext = Record<string, unknown>;

const apiBase = import.meta.env.VITE_HWE_API_BASE ?? 'http://127.0.0.1:8711';

export async function getProjects(includeArchived = false): Promise<{ projects: ProjectRecord[]; default_workspace_root: string | null }> {
  const query = includeArchived ? '?include_archived=true' : '';
  return request(`/api/projects${query}`);
}

export async function getConfig(): Promise<ConfigStatus> {
  return request('/api/config');
}

export async function getAIProviders(): Promise<AIProvider[]> {
  return request('/api/ai/providers');
}

export async function requestAIAssist(provider: string, target: AIAssistTarget, messages: AIAssistMessage[], draft: Record<string, unknown>, context: AIAssistContext = {}): Promise<AIAssistResponse> {
  return request('/api/ai/assist', {
    method: 'POST',
    body: JSON.stringify({ provider, target, messages, draft, context }),
  });
}

export async function createProject(input: CreateProjectInput): Promise<ProjectRecord> {
  return request('/api/projects', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function archiveProject(projectRef: string, projectId: string): Promise<ProjectRecord> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/archive?project_id=${encodeURIComponent(projectId)}`, {
    method: 'POST',
  });
}

export async function restoreProject(projectRef: string, projectId: string): Promise<ProjectRecord> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/restore?project_id=${encodeURIComponent(projectId)}`, {
    method: 'POST',
  });
}

export async function getWorkitems(projectRef: string, projectId: string, includeArchived = false): Promise<Workitem[]> {
  const archivedQuery = includeArchived ? '&include_archived=true' : '';
  return request(`/api/projects/${encodeURIComponent(projectRef)}/workitems?project_id=${encodeURIComponent(projectId)}${archivedQuery}`);
}

export async function archiveWorkitem(projectRef: string, projectId: string, workitemId: string): Promise<Workitem> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/workitems/${encodeURIComponent(workitemId)}/archive?project_id=${encodeURIComponent(projectId)}`, {
    method: 'POST',
  });
}

export async function restoreWorkitem(projectRef: string, projectId: string, workitemId: string): Promise<Workitem> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/workitems/${encodeURIComponent(workitemId)}/restore?project_id=${encodeURIComponent(projectId)}`, {
    method: 'POST',
  });
}

export async function createWorkitem(projectRef: string, projectId: string, input: CreateWorkitemInput): Promise<Workitem> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/workitems`, {
    method: 'POST',
    body: JSON.stringify({ ...input, project_id: projectId }),
  });
}

export async function getPromptTemplates(projectRef: string, projectId: string): Promise<PromptTemplate[]> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/prompt-templates?project_id=${encodeURIComponent(projectId)}`);
}

export async function getWorkflowTemplates(projectRef: string, projectId: string): Promise<WorkflowTemplate[]> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/workflow-templates?project_id=${encodeURIComponent(projectId)}`);
}

export async function getPublicPromptTemplates(): Promise<PromptTemplate[]> {
  return request('/api/prompt-templates');
}

export async function createPromptTemplate(projectRef: string, projectId: string, input: CreatePromptTemplateInput): Promise<PromptTemplate> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/prompt-templates`, {
    method: 'POST',
    body: JSON.stringify({ ...input, project_id: projectId }),
  });
}

export async function publishPromptTemplate(input: CreatePromptTemplateInput): Promise<PromptTemplate> {
  return request('/api/prompt-templates', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function deleteProjectPromptTemplate(projectRef: string, projectId: string, role: string, name: string): Promise<{ deleted: boolean }> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/prompt-templates/${encodeURIComponent(role)}/${encodeURIComponent(name)}?project_id=${encodeURIComponent(projectId)}`, {
    method: 'DELETE',
  });
}

export async function deletePublicPromptTemplate(role: string, name: string): Promise<{ deleted: boolean }> {
  return request(`/api/prompt-templates/${encodeURIComponent(role)}/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

export async function getDashboard(projectRef: string, projectId: string, workitemId: string): Promise<Dashboard> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/workitems/${encodeURIComponent(workitemId)}/dashboard?project_id=${encodeURIComponent(projectId)}`);
}

export async function runWorkitem(projectRef: string, projectId: string, workitemId: string): Promise<RunRequest> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/workitems/${encodeURIComponent(workitemId)}/run`, {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId, max_tasks: 1 }),
  });
}

export async function runTask(projectRef: string, projectId: string, taskId: string): Promise<RunRequest> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/tasks/${encodeURIComponent(taskId)}/run`, {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId }),
  });
}

export async function getRunRequest(projectRef: string, projectId: string, requestId: string): Promise<RunRequest> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/run-requests/${encodeURIComponent(requestId)}?project_id=${encodeURIComponent(projectId)}`);
}

export async function planWorkitem(projectRef: string, projectId: string, workitemId: string, workflowTemplateId: string, parameters: Record<string, string> = {}): Promise<{ workflow: Workflow; task: Task; tasks: Task[] }> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/workitems/${encodeURIComponent(workitemId)}/plan`, {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId, workflow_template_id: workflowTemplateId, parameters }),
  });
}

export async function materializePlan(
  projectRef: string,
  projectId: string,
  taskId: string,
  input: { workflow_template_id: string; parameters?: Record<string, string>; prompt_template_ref?: string; prompt_text?: string; profile?: string | null },
): Promise<{ created: Task[]; skipped: Task[]; tasks: Task[] }> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/tasks/${encodeURIComponent(taskId)}/materialize-plan`, {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId, ...input }),
  });
}

export async function retryTask(projectRef: string, taskId: string, reason = 'ui-retry'): Promise<Task> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/tasks/${encodeURIComponent(taskId)}/retry`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });
}

export async function releaseTask(projectRef: string, taskId: string, reason = 'ui-release'): Promise<Task> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/tasks/${encodeURIComponent(taskId)}/release`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });
}

export async function updateTask(projectRef: string, taskId: string, input: UpdateTaskInput): Promise<Task> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/tasks/${encodeURIComponent(taskId)}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export async function reassignTask(projectRef: string, taskId: string, input: { project_id: string; profile: string | null; reason?: string }): Promise<Task> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/tasks/${encodeURIComponent(taskId)}/reassign`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function getTaskPromptPreview(projectRef: string, projectId: string, taskId: string): Promise<TaskPromptPreview> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/tasks/${encodeURIComponent(taskId)}/prompt-preview?project_id=${encodeURIComponent(projectId)}`);
}

export async function completeTask(projectRef: string, taskId: string, status: string, result: Record<string, unknown>): Promise<Task> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/tasks/${encodeURIComponent(taskId)}/complete`, {
    method: 'POST',
    body: JSON.stringify({ status, result }),
  });
}

export async function getTaskRuns(projectRef: string, taskId: string): Promise<TaskRun[]> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/tasks/${encodeURIComponent(taskId)}/runs`);
}

export async function getRunLog(projectRef: string, runId: string, stream: RunLog['stream']): Promise<RunLog> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/runs/${encodeURIComponent(runId)}/logs?stream=${stream}`);
}

export async function getRunTimeline(projectRef: string, runId: string): Promise<RunTimeline> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/runs/${encodeURIComponent(runId)}/timeline`);
}

export async function answerHumanAction(projectRef: string, actionId: string, text: string): Promise<HumanAction> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/human-actions/${encodeURIComponent(actionId)}/answer`, {
    method: 'POST',
    body: JSON.stringify({ text, by: 'hwe-ui' }),
  });
}

export async function approveHumanAction(projectRef: string, actionId: string, text: string): Promise<HumanAction> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/human-actions/${encodeURIComponent(actionId)}/approve`, {
    method: 'POST',
    body: JSON.stringify({ text, by: 'hwe-ui' }),
  });
}

export async function rejectHumanAction(projectRef: string, actionId: string, reason: string): Promise<HumanAction> {
  return request(`/api/projects/${encodeURIComponent(projectRef)}/human-actions/${encodeURIComponent(actionId)}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason, by: 'hwe-ui' }),
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}