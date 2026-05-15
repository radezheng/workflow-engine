import { useState } from 'react';
import { FileText, RefreshCw, Save } from 'lucide-react';
import type { PromptTemplate, RunLog, RunTimeline, RunView, Task, TaskRun } from '../../api';
import { PromptTemplatePicker } from '../prompt-templates/PromptTemplatePicker';
import { StatusPill } from '../common/StatusPill';
import { MarkdownPreview } from '../common/MarkdownPreview';
import { formatUtc8 } from '../../lib/formatTime';

type TaskDetailPanelProps = {
  task: Task | null;
  runs: TaskRun[];
  loadingRuns: boolean;
  selectedRun: TaskRun | null;
  stream: RunView;
  log: RunLog | null;
  timeline: RunTimeline | null;
  promptPreview: string;
  promptPreviewLoading: boolean;
  refreshingLogs: boolean;
  disabled: boolean;
  profiles: string[];
  promptTemplates: PromptTemplate[];
  onSelectRun: (run: TaskRun) => void;
  onStreamChange: (stream: RunView) => void;
  onRefreshLogs: () => void;
  onUpdateTask: (task: Task, input: { profile: string | null; prompt_template_ref?: string | null; prompt_text?: string | null }) => Promise<void>;
  onSavePromptToProject: (input: { role: string; name: string; body: string }) => Promise<PromptTemplate | void>;
  onSavePromptToPublic: (input: { role: string; name: string; body: string }) => Promise<PromptTemplate | void>;
  onDeletePrompt: (template: PromptTemplate) => Promise<void>;
};

function promptLogText(text: string) {
  const trimmedStart = text.trimStart();
  if (!trimmedStart.startsWith('{')) return text;
  const closingIndex = trimmedStart.indexOf('\n}');
  if (closingIndex === -1) return text;
  const candidate = `${trimmedStart.slice(0, closingIndex + 2)}`;
  try {
    const parsed = JSON.parse(candidate);
    if (parsed && typeof parsed === 'object' && 'profile' in parsed) {
      return trimmedStart.slice(closingIndex + 2).trimStart();
    }
  } catch {
    return text;
  }
  return text;
}

function meaningfulRunResult(result: Record<string, unknown>) {
  const { profile: _profile, ...rest } = result;
  return rest;
}

function compactToolArguments(value: string) {
  if (!value) return '';
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function timelineEmptyText(timeline: RunTimeline | null, activeRun: TaskRun | null, loadingRuns: boolean) {
  if (!activeRun) return loadingRuns ? 'Loading runs' : 'No runs for this task yet';
  if (!timeline) return 'Loading timeline';
  if (timeline.status === 'missing_session_id') return 'No Hermes session id was found in this run.';
  if (timeline.status === 'missing_session_log') return `No Hermes session log was found for ${timeline.session_id ?? 'this run'}.`;
  return 'No timeline events';
}

export function TaskDetailPanel({ task, runs, loadingRuns, selectedRun, stream, log, timeline, promptPreview, promptPreviewLoading, refreshingLogs, disabled, profiles, promptTemplates, onSelectRun, onStreamChange, onRefreshLogs, onUpdateTask, onSavePromptToProject, onSavePromptToPublic, onDeletePrompt }: TaskDetailPanelProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [draftProfile, setDraftProfile] = useState<string | null>(null);
  const [draftPromptRef, setDraftPromptRef] = useState('');
  const [saving, setSaving] = useState(false);
  if (!task) {
    return <p className="empty-state">Select a task</p>;
  }
  const activeRun = selectedRun ?? runs[0] ?? null;
  const canEditProfile = !disabled && ['pending', 'ready'].includes(task.status);
  const canEditPrompt = canEditProfile && task.attempt === 0;
  const profileValue = draftProfile ?? task.profile ?? '';
  const promptRefValue = draftPromptRef || task.prompt_template_ref || '';
  const visibleResult = activeRun ? meaningfulRunResult(activeRun.result) : {};

  async function saveTaskEdit() {
    if (!task) return;
    setSaving(true);
    try {
      await onUpdateTask(task, {
        profile: profileValue.trim() || null,
        prompt_template_ref: canEditPrompt ? promptRefValue.trim() || null : undefined,
        prompt_text: canEditPrompt ? task.prompt_text : undefined,
      });
      setDraftProfile(null);
      setDraftPromptRef('');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="task-detail">
      <div className="detail-header">
        <div>
          <StatusPill status={task.status} />
          <h4>{task.title}</h4>
          <p>{task.id}</p>
        </div>
        <div className="detail-meta" aria-label="Task metadata">
          <span>{task.profile ?? 'default'}</span>
          <span>{task.kind}</span>
          <span>p{task.priority}</span>
          <span>{task.risk_level}</span>
        </div>
      </div>
      {canEditProfile && (
        <div className="task-edit-bar">
          <label>
            <span>Profile</span>
            <select value={profileValue} onChange={(event) => setDraftProfile(event.target.value)} disabled={saving}>
              <option value="">default</option>
              {profiles.map((profile) => <option key={profile} value={profile}>{profile}</option>)}
            </select>
          </label>
          <button type="button" className="secondary-button prompt-ref-button" disabled={saving || !canEditPrompt} onClick={() => setPickerOpen(true)} title="Choose task prompt">
            <FileText size={15} />
            {promptRefValue || 'No prompt template'}
          </button>
          <button type="button" className="primary-button" disabled={saving} onClick={() => void saveTaskEdit()} title="Save task changes">
            <Save size={15} />
            Save
          </button>
        </div>
      )}
      <div className="task-prompt-preview" aria-label="Rendered task prompt">
        {promptPreviewLoading ? <p className="markdown-empty">Loading prompt preview</p> : <MarkdownPreview text={promptPreview} emptyText="No prompt preview available" />}
      </div>
      <div className="run-controls">
        <div className="run-select-row">
          <select
            value={activeRun?.id ?? ''}
            onChange={(event) => {
              const run = runs.find((item) => item.id === event.target.value);
              if (run) onSelectRun(run);
            }}
            disabled={!runs.length}
            title="Task run"
          >
            {!runs.length && <option value="">{loadingRuns ? 'Loading runs' : 'No runs'}</option>}
            {runs.map((run) => (
              <option key={run.id} value={run.id}>{run.status} · attempt result · {formatUtc8(run.started_at)}</option>
            ))}
          </select>
        </div>
        <div className="run-tab-row">
          <div className="stream-tabs" role="tablist" aria-label="Run log stream">
            {(['stdout', 'stderr', 'prompt', 'timeline'] as const).map((item) => (
              <button key={item} className={stream === item ? 'selected' : ''} onClick={() => onStreamChange(item)}>{item}</button>
            ))}
          </div>
          <button type="button" className="secondary-button" disabled={refreshingLogs} onClick={onRefreshLogs} title="Refresh task runs and current log">
            <RefreshCw size={15} className={refreshingLogs ? 'spin-icon' : undefined} />
            Refresh
          </button>
        </div>
      </div>
      {activeRun && (
        <div className="run-summary">
          <span>{activeRun.status}</span>
          <span>exit {activeRun.exit_code ?? 'n/a'}</span>
          <span>{formatUtc8(activeRun.started_at)}</span>
        </div>
      )}
      {Object.keys(visibleResult).length > 0 && (
        <pre className="run-result">{JSON.stringify(visibleResult, null, 2)}</pre>
      )}
      {stream === 'timeline' ? (
        <div className="timeline-view" aria-label="Hermes session timeline">
          {timeline?.session_id && (
            <div className="timeline-meta">
              <span>session {timeline.session_id}</span>
              <span>{timeline.status}</span>
              {timeline.path && <span>{timeline.path}</span>}
            </div>
          )}
          {timeline?.events.length ? timeline.events.map((event) => (
            <article key={event.index} className={`timeline-event role-${event.role}`}>
              <header>
                <span>{event.role}</span>
                {event.timestamp && <time>{formatUtc8(event.timestamp)}</time>}
                {event.finish_reason && <span>{event.finish_reason}</span>}
              </header>
              {event.tool_call_id && <p className="timeline-tool-id">tool result · {event.tool_call_id}</p>}
              {event.content && <pre>{event.content}</pre>}
              {event.tool_calls.map((toolCall, index) => (
                <div key={`${event.index}-${toolCall.id ?? index}`} className="timeline-tool-call">
                  <strong>{toolCall.name || toolCall.type || 'tool call'}</strong>
                  {toolCall.id && <span>{toolCall.id}</span>}
                  {toolCall.arguments && <pre>{compactToolArguments(toolCall.arguments)}</pre>}
                </div>
              ))}
            </article>
          )) : <p className="markdown-empty">{timelineEmptyText(timeline, activeRun, loadingRuns)}</p>}
          {timeline?.status === 'missing_session_log' && timeline.searched_paths?.length ? (
            <pre className="timeline-searched-paths">{timeline.searched_paths.join('\n')}</pre>
          ) : null}
        </div>
      ) : stream === 'prompt' ? (
        <div className="run-prompt-preview" aria-label="Rendered run prompt">
          <MarkdownPreview text={activeRun ? promptLogText(log?.text || '') : ''} emptyText={activeRun ? 'No prompt content' : loadingRuns ? 'Loading runs' : 'No runs for this task yet'} />
        </div>
      ) : (
        <pre className="log-viewer">{activeRun ? log?.text || 'No log content' : loadingRuns ? 'Loading runs' : 'No runs for this task yet'}</pre>
      )}
      <PromptTemplatePicker
        open={pickerOpen}
        title="Choose Task Prompt"
        templates={promptTemplates}
        selectedRef={promptRefValue}
        disabled={saving || disabled || !canEditPrompt}
        onClose={() => setPickerOpen(false)}
        onSelect={(promptTemplateRef) => {
          setDraftPromptRef(promptTemplateRef);
          setPickerOpen(false);
        }}
        onSaveProject={onSavePromptToProject}
        onSavePublic={onSavePromptToPublic}
        onDelete={onDeletePrompt}
      />
    </div>
  );
}