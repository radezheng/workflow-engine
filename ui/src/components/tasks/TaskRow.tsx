import { ListPlus, Pause, Play, RotateCcw } from 'lucide-react';
import type { Task } from '../../api';
import { StatusPill } from '../common/StatusPill';

type TaskRowProps = {
  task: Task;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
  onRun: () => void;
  onRetry: () => void;
  onRelease: () => void;
  canMaterializePlan: boolean;
  onMaterializePlan: () => void;
};

function actionHint(task: Task) {
  if (task.status === 'running') return 'Running in a worker';
  if (task.status === 'pending') return 'Waiting on dependencies';
  if (task.status === 'waiting_for_info' || task.status === 'waiting_for_approval') return 'Needs human input';
  return '';
}

export function TaskRow({ task, selected, disabled, onSelect, onRun, onRetry, onRelease, canMaterializePlan, onMaterializePlan }: TaskRowProps) {
  const hint = actionHint(task);
  return (
    <article className={selected ? 'task-row selected' : 'task-row'}>
      <button className="task-main task-select" onClick={onSelect} title="Open task detail">
        <StatusPill status={task.status} />
        <div>
          <h4>{task.title}</h4>
          <p>{task.kind} · {task.profile ?? 'default'} · attempt {task.attempt}</p>
        </div>
      </button>
      <div className="task-actions">
        {task.status === 'ready' && (
          <button aria-label="Run task" title="Run this ready task" disabled={disabled} onClick={onRun}>
            <Play size={15} />
          </button>
        )}
        {['failed', 'cancelled'].includes(task.status) && (
          <button title="Retry failed task" disabled={disabled} onClick={onRetry}>
            <RotateCcw size={15} />
          </button>
        )}
        {task.status === 'running' && (
          <button title="Release abandoned run" disabled={disabled} onClick={onRelease}>
            <Pause size={15} />
          </button>
        )}
        {canMaterializePlan && (
          <button aria-label="Break down plan" title="Break down plan" disabled={disabled} onClick={onMaterializePlan}>
            <ListPlus size={15} />
          </button>
        )}
        {hint && <span className="task-action-hint">{hint}</span>}
      </div>
    </article>
  );
}