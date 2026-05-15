import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Clock3,
  FileText,
  Hand,
  ListChecks,
  Settings,
  ShieldCheck,
  TerminalSquare,
} from 'lucide-react';
import {
  Dashboard,
  CreateProjectInput,
  CreateWorkitemInput,
  ProjectRecord,
  PromptTemplate,
  RunLog,
  RunSummary,
  RunTimeline,
  RunView,
  Task,
  TaskRun,
  WorkflowAction,
  WorkflowTemplate,
  Workitem,
  answerHumanAction,
  approveHumanAction,
  archiveProject,
  archiveWorkitem,
  createProject,
  createPromptTemplate,
  createWorkitem,
  deleteProjectPromptTemplate,
  deletePublicPromptTemplate,
  getConfig,
  getDashboard,
  getProjects,
  getPromptTemplates,
  getRunLog,
  getRunTimeline,
  getTaskPromptPreview,
  getTaskRuns,
  getWorkflowTemplates,
  getWorkitems,
  materializePlan,
  planWorkitem,
  publishPromptTemplate,
  rejectHumanAction,
  reassignTask,
  releaseTask,
  restoreProject,
  restoreWorkitem,
  retryTask,
  runTask,
  runWorkitem,
  updateTask,
} from './api';
import { Metric } from './components/common/Metric';
import { Notice } from './components/common/Notice';
import { PanelTitle } from './components/common/PanelTitle';
import { EventList } from './components/events/EventList';
import { HumanActionList } from './components/human-actions/HumanActionList';
import { Sidebar } from './components/layout/Sidebar';
import type { ConsoleView } from './components/layout/Sidebar';
import { PromptTemplatesPanel } from './components/prompt-templates/PromptTemplatesPanel';
import { SettingsPanel } from './components/settings/SettingsPanel';
import { Topbar } from './components/layout/Topbar';
import { PlanMaterializeDialog } from './components/tasks/PlanMaterializeDialog';
import { TaskDetailPanel } from './components/tasks/TaskDetailPanel';
import { TaskQueue } from './components/tasks/TaskQueue';
import { WorkitemCreateForm } from './components/workitems/WorkitemCreateForm';
import { WorkitemList } from './components/workitems/WorkitemList';
import { summarizeTasks } from './lib/summarizeTasks';

type LoadState = 'idle' | 'loading' | 'ready' | 'error';

function runSummaryMessage(summary: RunSummary, taskTitle?: string) {
  if (summary.tasks_started === 0) {
    if (summary.blocked.length) return `Run Next: no ready task. ${summary.blocked.length} task(s) are blocked by dependencies.`;
    if (summary.open.length) return `Run Next: no ready task. ${summary.open.length} task(s) are still open but not ready.`;
    return 'Run Next: no ready task. This workitem may already be complete or needs planning/materialization first.';
  }
  const target = taskTitle ? ` ${taskTitle}` : '';
  if (summary.tasks_failed > 0) return `Run Next:${target} failed. Check Task Detail logs and Events.`;
  if (summary.waiting_for_human > 0) return `Run Next:${target} is waiting for human input.`;
  if (summary.tasks_succeeded > 0) return `Run Next:${target} succeeded.`;
  return `Run Next: started ${summary.tasks_started} task(s).`;
}

export function App() {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [workitems, setWorkitems] = useState<Workitem[]>([]);
  const [promptTemplates, setPromptTemplates] = useState<PromptTemplate[]>([]);
  const [workflowTemplates, setWorkflowTemplates] = useState<WorkflowTemplate[]>([]);
  const [profiles, setProfiles] = useState<string[]>([]);
  const [selectedProject, setSelectedProject] = useState<ProjectRecord | null>(null);
  const [selectedWorkitem, setSelectedWorkitem] = useState<Workitem | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [taskRuns, setTaskRuns] = useState<TaskRun[]>([]);
  const [taskRunsLoading, setTaskRunsLoading] = useState(false);
  const [selectedRun, setSelectedRun] = useState<TaskRun | null>(null);
  const [logStream, setLogStream] = useState<RunView>('stdout');
  const [runLog, setRunLog] = useState<RunLog | null>(null);
  const [runTimeline, setRunTimeline] = useState<RunTimeline | null>(null);
  const [promptPreview, setPromptPreview] = useState('');
  const [promptPreviewLoading, setPromptPreviewLoading] = useState(false);
  const [taskDetailRefreshing, setTaskDetailRefreshing] = useState(false);
  const [loadState, setLoadState] = useState<LoadState>('idle');
  const [message, setMessage] = useState('');
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [autoRun, setAutoRun] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [showArchivedWorkitems, setShowArchivedWorkitems] = useState(false);
  const [materializeTask, setMaterializeTask] = useState<Task | null>(null);
  const [materializeWorkflowAction, setMaterializeWorkflowAction] = useState<WorkflowAction | null>(null);
  const [materializePromptTemplateRef, setMaterializePromptTemplateRef] = useState('');
  const [materializePromptText, setMaterializePromptText] = useState('');
  const autoRunRef = useRef(false);
  const [activeView, setActiveView] = useState<ConsoleView>('workflow');
  const [settingsRefreshToken, setSettingsRefreshToken] = useState(0);
  const [promptTemplatesRefreshToken, setPromptTemplatesRefreshToken] = useState(0);

  function handleAutoRunChange(checked: boolean) {
    autoRunRef.current = checked;
    setAutoRun(checked);
  }

  function clearRunSelection() {
    setTaskRuns([]);
    setTaskRunsLoading(false);
    setSelectedRun(null);
    setRunLog(null);
    setRunTimeline(null);
    setPromptPreview('');
    setPromptPreviewLoading(false);
  }

  function clearTaskSelection() {
    setSelectedTaskId(null);
    clearRunSelection();
  }

  function clearWorkitemSelection() {
    setSelectedWorkitem(null);
    setDashboard(null);
    setDashboardLoading(false);
    clearTaskSelection();
  }

  function handleSelectProject(project: ProjectRecord) {
    setActiveView('workflow');
    if (selectedProject?.id === project.id && selectedProject.project_ref === project.project_ref) {
      setMessage('');
      return;
    }
    setSelectedProject(project);
    setWorkitems([]);
    clearWorkitemSelection();
    setMessage('');
  }

  function handleSelectWorkitem(workitem: Workitem) {
    if (selectedWorkitem?.id === workitem.id) {
      return;
    }
    setSelectedWorkitem(workitem);
    setDashboard(null);
    setDashboardLoading(true);
    clearTaskSelection();
    setMessage('');
  }

  function handleSelectTask(task: Task) {
    if (selectedTaskId === task.id) {
      return;
    }
    setSelectedTaskId(task.id);
    clearRunSelection();
  }

  function handleViewChange(view: ConsoleView) {
    setActiveView(view);
    setMessage('');
    if (view === 'settings') setSettingsRefreshToken((current) => current + 1);
    if (view === 'prompt-templates') setPromptTemplatesRefreshToken((current) => current + 1);
  }

  function handleSidebarRefresh() {
    void refreshProjects();
    if (activeView === 'settings') setSettingsRefreshToken((current) => current + 1);
    if (activeView === 'prompt-templates') setPromptTemplatesRefreshToken((current) => current + 1);
  }

  const refreshProjects = useCallback(async () => {
    setLoadState('loading');
    try {
      const payload = await getProjects(showArchived);
      setProjects(payload.projects);
      setSelectedProject((current) => {
        if (!current) return payload.projects[0] ?? null;
        return payload.projects.find((project) => project.project_ref === current.project_ref && project.id === current.id) ?? payload.projects[0] ?? null;
      });
      setMessage(payload.projects.length ? '' : 'No project databases found.');
      setLoadState('ready');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
      setLoadState('error');
    }
  }, [showArchived]);

  useEffect(() => {
    void refreshProjects();
  }, [refreshProjects]);

  useEffect(() => {
    let active = true;
    void getConfig()
      .then((config) => { if (active) setProfiles(config.profiles); })
      .catch((error) => { if (active) setMessage(error instanceof Error ? error.message : String(error)); });
    return () => { active = false; };
  }, []);

  const refreshWorkitems = useCallback(async (isCurrent: () => boolean = () => true) => {
    if (!selectedProject) {
      if (!isCurrent()) return;
      setWorkitems([]);
      setSelectedWorkitem(null);
      return;
    }
    const items = await getWorkitems(selectedProject.project_ref, selectedProject.id, showArchivedWorkitems);
    if (!isCurrent()) return;
    setWorkitems(items);
    setSelectedWorkitem((current) => current ? items.find((item) => item.id === current.id) ?? items[0] ?? null : items[0] ?? null);
  }, [selectedProject, showArchivedWorkitems]);

  useEffect(() => {
    let active = true;
    void refreshWorkitems(() => active).catch((error) => {
      if (active) setMessage(error instanceof Error ? error.message : String(error));
    });
    return () => { active = false; };
  }, [refreshWorkitems]);

  useEffect(() => {
    if (!selectedProject) {
      setPromptTemplates([]);
      setWorkflowTemplates([]);
      return;
    }
    let active = true;
    void Promise.all([
      getPromptTemplates(selectedProject.project_ref, selectedProject.id),
      getWorkflowTemplates(selectedProject.project_ref, selectedProject.id),
    ])
      .then(([templates, workflows]) => {
        if (!active) return;
        setPromptTemplates(templates);
        setWorkflowTemplates(workflows);
      })
      .catch((error) => {
        if (active) setMessage(error instanceof Error ? error.message : String(error));
      });
    return () => { active = false; };
  }, [selectedProject]);

  const refreshPromptTemplates = useCallback(async () => {
    if (!selectedProject) return [];
    const templates = await getPromptTemplates(selectedProject.project_ref, selectedProject.id);
    setPromptTemplates(templates);
    return templates;
  }, [selectedProject]);

  const refreshDashboard = useCallback(async (isCurrent: () => boolean = () => true) => {
    if (!selectedProject || !selectedWorkitem) {
      if (!isCurrent()) return;
      setDashboard(null);
      setDashboardLoading(false);
      return;
    }
    setDashboardLoading(true);
    try {
      const payload = await getDashboard(selectedProject.project_ref, selectedProject.id, selectedWorkitem.id);
      if (!isCurrent()) return;
      setDashboard(payload);
      setSelectedTaskId((current) => current && payload.tasks.some((task) => task.id === current) ? current : payload.tasks[0]?.id ?? null);
    } finally {
      if (isCurrent()) setDashboardLoading(false);
    }
  }, [selectedProject, selectedWorkitem]);

  useEffect(() => {
    let active = true;
    void refreshDashboard(() => active).catch((error) => {
      if (active) setMessage(error instanceof Error ? error.message : String(error));
    });
    return () => { active = false; };
  }, [refreshDashboard]);

  const currentDashboard = dashboard && selectedWorkitem && dashboard.workitem.id === selectedWorkitem.id ? dashboard : null;
  const selectedTask = currentDashboard?.tasks.find((task) => task.id === selectedTaskId) ?? null;
  const selectedProjectArchived = selectedProject?.status === 'archived';
  const selectedWorkitemArchived = selectedWorkitem?.status === 'archived';
  const taskCounts = useMemo(() => summarizeTasks(currentDashboard?.tasks ?? []), [currentDashboard]);
  const taskQueueLoading = Boolean(selectedWorkitem && (dashboardLoading || !currentDashboard));
  const selectedTaskEvents = useMemo(() => {
    const events = currentDashboard?.events ?? [];
    if (!selectedTask) return events;
    const runIds = new Set(taskRuns.map((run) => run.id));
    return events.filter((event) => event.task_id === selectedTask.id || (event.run_id !== null && runIds.has(event.run_id)));
  }, [currentDashboard, selectedTask, taskRuns]);

  const refreshTaskRuns = useCallback(async (isCurrent: () => boolean = () => true) => {
    if (!selectedProject || !selectedTaskId) {
      if (!isCurrent()) return;
      setTaskRuns([]);
      setTaskRunsLoading(false);
      setSelectedRun(null);
      setRunLog(null);
      setRunTimeline(null);
      return;
    }
    setTaskRunsLoading(true);
    try {
      const runs = await getTaskRuns(selectedProject.project_ref, selectedTaskId);
      if (!isCurrent()) return;
      setTaskRuns(runs);
      setSelectedRun((current) => current && runs.some((run) => run.id === current.id) ? current : runs[0] ?? null);
    } finally {
      if (isCurrent()) setTaskRunsLoading(false);
    }
  }, [selectedProject, selectedTaskId]);

  useEffect(() => {
    let active = true;
    void refreshTaskRuns(() => active).catch((error) => {
      if (active) setMessage(error instanceof Error ? error.message : String(error));
    });
    return () => { active = false; };
  }, [refreshTaskRuns]);

  useEffect(() => {
    if (!selectedProject || !selectedRun) {
      setRunLog(null);
      setRunTimeline(null);
      return;
    }
    let active = true;
    if (logStream === 'timeline') {
      setRunLog(null);
      void getRunTimeline(selectedProject.project_ref, selectedRun.id)
        .then((timeline) => { if (active) setRunTimeline(timeline); })
        .catch((error) => { if (active) setMessage(error instanceof Error ? error.message : String(error)); });
    } else {
      setRunTimeline(null);
      void getRunLog(selectedProject.project_ref, selectedRun.id, logStream)
        .then((log) => { if (active) setRunLog(log); })
        .catch((error) => { if (active) setMessage(error instanceof Error ? error.message : String(error)); });
    }
    return () => { active = false; };
  }, [selectedProject, selectedRun, logStream]);

  useEffect(() => {
    if (!selectedProject || !selectedTaskId) {
      setPromptPreview('');
      setPromptPreviewLoading(false);
      return;
    }
    let active = true;
    setPromptPreviewLoading(true);
    void getTaskPromptPreview(selectedProject.project_ref, selectedProject.id, selectedTaskId)
      .then((preview) => { if (active) setPromptPreview(preview.text); })
      .catch((error) => { if (active) setPromptPreview(error instanceof Error ? error.message : String(error)); })
      .finally(() => { if (active) setPromptPreviewLoading(false); });
    return () => { active = false; };
  }, [selectedProject, selectedTaskId]);

  async function runAction(label: string, action: () => Promise<unknown>) {
    setBusyAction(label);
    setMessage('');
    try {
      await action();
      await refreshDashboard();
      await refreshWorkitems();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRunNext() {
    if (!selectedProject || !selectedWorkitem) return;
    const project = selectedProject;
    const workitem = selectedWorkitem;
    let beforeTasks = new Map((currentDashboard?.tasks ?? []).map((task) => [task.id, task]));
    setBusyAction('run');
    setMessage(autoRunRef.current ? 'Auto Run: running ready tasks...' : 'Running next ready task...');
    let refreshTimer: number | null = null;
    try {
      refreshTimer = window.setInterval(() => {
        void getDashboard(project.project_ref, project.id, workitem.id)
          .then((payload) => setDashboard(payload))
          .catch((error) => setMessage(error instanceof Error ? error.message : String(error)));
      }, 2000);
      for (let runCount = 0; runCount < 100; runCount += 1) {
        const summary = await runWorkitem(project.project_ref, project.id, workitem.id);
        const payload = await getDashboard(project.project_ref, project.id, workitem.id);
        const changedTask = payload.tasks.find((task) => (beforeTasks.get(task.id)?.attempt ?? task.attempt) < task.attempt)
          ?? payload.tasks.find((task) => beforeTasks.get(task.id)?.status !== task.status);
        setDashboard(payload);
        await refreshWorkitems();
        if (changedTask) {
          setSelectedTaskId(changedTask.id);
          setSelectedRun(null);
          setRunLog(null);
        }
        setMessage(runSummaryMessage(summary, changedTask?.title));
        beforeTasks = new Map(payload.tasks.map((task) => [task.id, task]));
        if (!autoRunRef.current || summary.tasks_started === 0 || summary.tasks_failed > 0 || summary.waiting_for_human > 0) break;
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (refreshTimer !== null) window.clearInterval(refreshTimer);
      setBusyAction(null);
    }
  }

  async function handleRunTask(task: Task) {
    if (!selectedProject || !selectedWorkitem) return;
    const project = selectedProject;
    const workitem = selectedWorkitem;
    setSelectedTaskId(task.id);
    setBusyAction(`run:${task.id}`);
    setMessage(`Running ${task.title}...`);
    let refreshTimer: number | null = null;
    try {
      refreshTimer = window.setInterval(() => {
        void getDashboard(project.project_ref, project.id, workitem.id)
          .then((payload) => setDashboard(payload))
          .catch((error) => setMessage(error instanceof Error ? error.message : String(error)));
      }, 2000);
      const summary = await runTask(project.project_ref, project.id, task.id);
      const payload = await getDashboard(project.project_ref, project.id, workitem.id);
      setDashboard(payload);
      await refreshWorkitems();
      setSelectedTaskId(task.id);
      setSelectedRun(null);
      setRunLog(null);
      setMessage(runSummaryMessage(summary, task.title));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (refreshTimer !== null) window.clearInterval(refreshTimer);
      setBusyAction(null);
    }
  }

  async function handleOpenMaterializePlan(task: Task) {
    if (!selectedProject || !selectedWorkitem) return;
    setBusyAction(`materialize-open:${task.id}`);
    setMessage('');
    try {
      const runs = await getTaskRuns(selectedProject.project_ref, task.id);
      const planRun = runs.find((run) => run.status === 'succeeded' && run.stdout_path);
      if (!planRun?.stdout_path) {
        throw new Error('Plan task has no successful stdout run to materialize.');
      }
      const action = task.workflow_actions?.materialize_plan;
      if (!action?.workflow_template_id || !action.prompt_template_ref) {
        throw new Error('No workflow template materialization action is available for this task.');
      }
      setMaterializeTask(task);
      setMaterializeWorkflowAction(action);
      setMaterializePromptTemplateRef(action.prompt_template_ref);
      setMaterializePromptText('');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleSubmitMaterializePlan() {
    if (!selectedProject || !materializeTask) return;
    const task = materializeTask;
    const action = materializeWorkflowAction;
    if (!action) return;
    await runAction(`materialize:${task.id}`, async () => {
      const result = await materializePlan(selectedProject.project_ref, selectedProject.id, task.id, {
        workflow_template_id: action.workflow_template_id,
        parameters: action.parameters ?? {},
        profile: action.profile,
        prompt_template_ref: materializePromptTemplateRef,
        prompt_text: materializePromptText.trim() || undefined,
      });
      const nextTask = result.created[0] ?? result.skipped[0];
      if (nextTask) {
        setSelectedTaskId(nextTask.id);
        setSelectedRun(null);
        setRunLog(null);
      }
      setMaterializeTask(null);
      setMaterializeWorkflowAction(null);
    });
  }

  async function handleCreateProject(input: CreateProjectInput) {
    setBusyAction('create-project');
    setMessage('');
    try {
      const createdProject = await createProject(input);
      const payload = await getProjects(showArchived);
      const selected = payload.projects.find((project) => project.project_ref === createdProject.project_ref && project.id === createdProject.id) ?? createdProject;
      setProjects(payload.projects);
      setActiveView('workflow');
      setSelectedProject(selected);
      setWorkitems([]);
      clearWorkitemSelection();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
      throw error;
    } finally {
      setBusyAction(null);
    }
  }

  async function handleArchiveProject(project: ProjectRecord) {
    if (!window.confirm(`Archive ${project.name}? Its files and workflow history will be kept.`)) return;
    setBusyAction(`archive:${project.id}`);
    setMessage('Archiving project...');
    try {
      await archiveProject(project.project_ref, project.id);
      const payload = await getProjects(showArchived);
      setProjects(payload.projects);
      const replacement = payload.projects.find((item) => item.project_ref === project.project_ref && item.id === project.id) ?? payload.projects[0] ?? null;
      setSelectedProject(replacement);
      if (!replacement || replacement.id !== selectedProject?.id || replacement.project_ref !== selectedProject?.project_ref) {
        setWorkitems([]);
        clearWorkitemSelection();
      }
      setMessage(`${project.name} archived.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRestoreProject(project: ProjectRecord) {
    setBusyAction(`restore:${project.id}`);
    setMessage('Restoring project...');
    try {
      await restoreProject(project.project_ref, project.id);
      const payload = await getProjects(showArchived);
      const restored = payload.projects.find((item) => item.project_ref === project.project_ref && item.id === project.id) ?? project;
      setProjects(payload.projects);
      setSelectedProject(restored);
      setMessage(`${project.name} restored.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleCreateWorkitem(input: CreateWorkitemInput) {
    if (!selectedProject) return;
    setBusyAction('create-workitem');
    setMessage('');
    try {
      const createdWorkitem = await createWorkitem(selectedProject.project_ref, selectedProject.id, input);
      const items = await getWorkitems(selectedProject.project_ref, selectedProject.id, showArchivedWorkitems);
      setWorkitems(items);
      setSelectedWorkitem(items.find((item) => item.id === createdWorkitem.id) ?? createdWorkitem);
      setDashboard(null);
      clearTaskSelection();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
      throw error;
    } finally {
      setBusyAction(null);
    }
  }

  async function handleArchiveWorkitem(workitem: Workitem) {
    if (!selectedProject) return;
    if (!window.confirm(`Archive ${workitem.title}? Its workflow history will be kept.`)) return;
    setBusyAction(`archive-workitem:${workitem.id}`);
    setMessage('Archiving workitem...');
    try {
      await archiveWorkitem(selectedProject.project_ref, selectedProject.id, workitem.id);
      const items = await getWorkitems(selectedProject.project_ref, selectedProject.id, showArchivedWorkitems);
      setWorkitems(items);
      const replacement = items.find((item) => item.id === workitem.id) ?? items[0] ?? null;
      setSelectedWorkitem(replacement);
      if (!replacement || replacement.id !== workitem.id) {
        setDashboard(null);
        clearTaskSelection();
      }
      setMessage(`${workitem.title} archived.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRestoreWorkitem(workitem: Workitem) {
    if (!selectedProject) return;
    setBusyAction(`restore-workitem:${workitem.id}`);
    setMessage('Restoring workitem...');
    try {
      await restoreWorkitem(selectedProject.project_ref, selectedProject.id, workitem.id);
      const items = await getWorkitems(selectedProject.project_ref, selectedProject.id, showArchivedWorkitems);
      setWorkitems(items);
      setSelectedWorkitem(items.find((item) => item.id === workitem.id) ?? workitem);
      setMessage(`${workitem.title} restored.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusyAction(null);
    }
  }

  async function handleSavePromptToProject(input: { role: string; name: string; body: string }) {
    if (!selectedProject) return;
    const saved = await createPromptTemplate(selectedProject.project_ref, selectedProject.id, { ...input, version: 'file', description: '', tags: [] });
    await refreshPromptTemplates();
    return saved;
  }

  async function handleSavePromptToPublic(input: { role: string; name: string; body: string }) {
    const saved = await publishPromptTemplate({ ...input, version: 'file', description: '', tags: [] });
    await refreshPromptTemplates();
    return saved;
  }

  async function handleDeletePrompt(template: PromptTemplate) {
    if (template.source === 'project') {
      if (!selectedProject) return;
      await deleteProjectPromptTemplate(selectedProject.project_ref, selectedProject.id, template.role, template.name);
    } else {
      await deletePublicPromptTemplate(template.role, template.name);
    }
    await refreshPromptTemplates();
  }

  async function handleUpdateTask(task: Task, input: { profile: string | null; prompt_template_ref?: string | null; prompt_text?: string | null }) {
    if (!selectedProject) return;
    const updated = task.attempt > 0
      ? await reassignTask(selectedProject.project_ref, task.id, { project_id: selectedProject.id, profile: input.profile, reason: 'ui-profile-reassign' })
      : await updateTask(selectedProject.project_ref, task.id, { project_id: selectedProject.id, ...input });
    setSelectedTaskId(updated.id);
    await refreshDashboard();
  }

  async function handleRefreshTaskDetail() {
    if (!selectedProject || !selectedWorkitem || !selectedTask) return;
    const project = selectedProject;
    const workitem = selectedWorkitem;
    const task = selectedTask;
    setTaskDetailRefreshing(true);
    setMessage('Refreshing task detail...');
    try {
      const payload = await getDashboard(project.project_ref, project.id, workitem.id);
      setDashboard(payload);
      const refreshedTask = payload.tasks.find((item) => item.id === task.id) ?? task;
      const runs = await getTaskRuns(project.project_ref, refreshedTask.id);
      setTaskRuns(runs);
      const activeRun = runs[0] ?? null;
      setSelectedRun(activeRun);
      if (activeRun) {
        if (logStream === 'timeline') {
          setRunTimeline(await getRunTimeline(project.project_ref, activeRun.id));
          setRunLog(null);
        } else {
          const latestLog = await getRunLog(project.project_ref, activeRun.id, logStream);
          setRunLog(latestLog);
          setRunTimeline(null);
        }
      } else {
        setRunLog(null);
        setRunTimeline(null);
      }
      const preview = await getTaskPromptPreview(project.project_ref, project.id, refreshedTask.id);
      setPromptPreview(preview.text);
      setMessage('Task detail refreshed.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setTaskDetailRefreshing(false);
    }
  }

  return (
    <main className="console-shell">
      <Sidebar
        projects={projects}
        selectedProject={selectedProject}
        activeView={activeView}
        loadState={loadState}
        busy={busyAction !== null}
        showArchived={showArchived}
        onRefresh={handleSidebarRefresh}
        onCreateProject={handleCreateProject}
        onSelectProject={handleSelectProject}
        onArchiveProject={(project) => void handleArchiveProject(project)}
        onRestoreProject={(project) => void handleRestoreProject(project)}
        onShowArchivedChange={setShowArchived}
        onViewChange={handleViewChange}
      />

      <section className="workspace">
        <Topbar
          selectedProject={selectedProject}
          selectedWorkitem={selectedWorkitem}
          disabled={!selectedProject || !selectedWorkitem || selectedProjectArchived || selectedWorkitemArchived || busyAction !== null}
          running={busyAction === 'run'}
          autoRun={autoRun}
          autoDisabled={!selectedProject || !selectedWorkitem || selectedProjectArchived || selectedWorkitemArchived}
          onAutoRunChange={handleAutoRunChange}
          onRunNext={() => void handleRunNext()}
        />

        <Notice message={message} />

        {activeView === 'workflow' && <><div className="metrics-row" aria-label="Task status summary">
          <Metric label="Ready" value={taskCounts.ready} tone="ready" />
          <Metric label="Running" value={taskCounts.running} tone="running" />
          <Metric label="Waiting" value={taskCounts.waiting} tone="waiting" />
          <Metric label="Failed" value={taskCounts.failed} tone="failed" />
          <Metric label="Done" value={taskCounts.done} tone="done" />
        </div>

        <div className="main-grid">
          <section className="panel workitems-panel" aria-label="Workitems">
            <PanelTitle icon={<ListChecks size={17} />} title="Workitems" />
            <WorkitemCreateForm
              disabled={busyAction !== null || !selectedProject || selectedProjectArchived}
              assistContext={selectedProject ? { project_ref: selectedProject.project_ref, project_id: selectedProject.id } : {}}
              onCreate={handleCreateWorkitem}
            />
            <WorkitemList
              workitems={workitems}
              selectedWorkitem={selectedWorkitem}
              workflowTemplates={workflowTemplates}
              disabled={busyAction !== null || !selectedProject || selectedProjectArchived}
              showArchived={showArchivedWorkitems}
              onSelectWorkitem={handleSelectWorkitem}
              onArchiveWorkitem={(workitem) => void handleArchiveWorkitem(workitem)}
              onRestoreWorkitem={(workitem) => void handleRestoreWorkitem(workitem)}
              onShowArchivedChange={setShowArchivedWorkitems}
              onPlanWorkitem={(workitem, workflowTemplateId, parameters) => selectedProject && void runAction(`plan:${workitem.id}`, async () => {
                setSelectedWorkitem(workitem);
                await planWorkitem(selectedProject.project_ref, selectedProject.id, workitem.id, workflowTemplateId, parameters);
              })}
            />
          </section>

          <section className="panel task-panel" aria-label="Tasks">
            <PanelTitle icon={<ShieldCheck size={17} />} title="Task Queue" />
            <TaskQueue
              tasks={currentDashboard?.tasks ?? []}
              selectedTask={selectedTask}
              loading={taskQueueLoading}
              disabled={busyAction !== null || !selectedProject || selectedProjectArchived || selectedWorkitemArchived}
              onSelect={handleSelectTask}
              onRun={(task) => void handleRunTask(task)}
              onRetry={(task) => selectedProject && void runAction(task.id, () => retryTask(selectedProject.project_ref, task.id))}
              onRelease={(task) => selectedProject && void runAction(task.id, () => releaseTask(selectedProject.project_ref, task.id))}
              onMaterializePlan={(task) => void handleOpenMaterializePlan(task)}
            />
          </section>
        </div>

        <div className="lower-grid">
          <section className="panel task-detail-panel" aria-label="Task details">
            <PanelTitle icon={<TerminalSquare size={17} />} title="Task Detail" />
            <TaskDetailPanel
              task={selectedTask}
              runs={taskRuns}
              loadingRuns={taskRunsLoading}
              selectedRun={selectedRun}
              stream={logStream}
              log={runLog}
              timeline={runTimeline}
              promptPreview={promptPreview}
              promptPreviewLoading={promptPreviewLoading}
              refreshingLogs={taskDetailRefreshing}
              disabled={selectedProjectArchived}
              profiles={profiles}
              promptTemplates={promptTemplates}
              onSelectRun={setSelectedRun}
              onStreamChange={setLogStream}
              onRefreshLogs={() => void handleRefreshTaskDetail()}
              onUpdateTask={handleUpdateTask}
              onSavePromptToProject={handleSavePromptToProject}
              onSavePromptToPublic={handleSavePromptToPublic}
              onDeletePrompt={handleDeletePrompt}
            />
          </section>

          <section className="panel" aria-label="Events">
            <PanelTitle icon={<Clock3 size={17} />} title={selectedTask ? 'Task Events' : 'Events'} />
            <EventList events={selectedTaskEvents} emptyText={selectedTask ? 'No events for selected task' : 'None'} />
          </section>

          <section className="panel" aria-label="Human actions">
            <PanelTitle icon={<Hand size={17} />} title="Human Actions" />
            <HumanActionList
              actions={currentDashboard?.human_actions ?? []}
              disabled={busyAction !== null || !selectedProject || selectedProjectArchived}
              assistContext={selectedProject ? { project_ref: selectedProject.project_ref, project_id: selectedProject.id } : {}}
              onAnswer={(action, text) => selectedProject && runAction(action.id, () => answerHumanAction(selectedProject.project_ref, action.id, text))}
              onApprove={(action, text) => selectedProject && runAction(action.id, () => approveHumanAction(selectedProject.project_ref, action.id, text))}
              onReject={(action, reason) => selectedProject && runAction(action.id, () => rejectHumanAction(selectedProject.project_ref, action.id, reason))}
            />
          </section>
        </div></>}

        <PlanMaterializeDialog
          task={materializeTask}
          templates={promptTemplates}
          promptTemplateRef={materializePromptTemplateRef}
          promptText={materializePromptText}
          disabled={busyAction !== null}
          onPromptTemplateRefChange={setMaterializePromptTemplateRef}
          onPromptTextChange={setMaterializePromptText}
          onClose={() => {
            setMaterializeTask(null);
            setMaterializeWorkflowAction(null);
          }}
          onSubmit={() => void handleSubmitMaterializePlan()}
        />

        {activeView === 'prompt-templates' && (
          <section aria-label="Prompt templates surface">
            <PanelTitle icon={<FileText size={17} />} title="Prompt Templates" />
            <PromptTemplatesPanel project={selectedProject} refreshToken={promptTemplatesRefreshToken} disabled={busyAction !== null || !selectedProject || selectedProjectArchived} onError={setMessage} />
          </section>
        )}

        {activeView === 'settings' && (
          <section aria-label="Settings surface">
            <PanelTitle icon={<Settings size={17} />} title="Settings" />
            <SettingsPanel refreshToken={settingsRefreshToken} />
          </section>
        )}
      </section>
    </main>
  );
}