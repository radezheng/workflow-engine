import type { Task } from '../../api';
import { TaskRow } from './TaskRow';

type TaskQueueProps = {
  tasks: Task[];
  selectedTask: Task | null;
  loading: boolean;
  disabled: boolean;
  onSelect: (task: Task) => void;
  onRun: (task: Task) => void;
  onRetry: (task: Task) => void;
  onRelease: (task: Task) => void;
  onMaterializePlan: (task: Task) => void;
};

export function TaskQueue({ tasks, selectedTask, loading, disabled, onSelect, onRun, onRetry, onRelease, onMaterializePlan }: TaskQueueProps) {
  if (loading) {
    return <p className="empty-state">Loading tasks</p>;
  }
  if (!tasks.length) {
    return <p className="empty-state">No tasks yet. Plan this workitem to create the first task.</p>;
  }
  return (
    <div className="task-table">
      {tasks.map((task) => (
        <TaskRow
          key={task.id}
          task={task}
          selected={task.id === selectedTask?.id}
          disabled={disabled}
          onSelect={() => onSelect(task)}
          onRun={() => onRun(task)}
          onRetry={() => onRetry(task)}
          onRelease={() => onRelease(task)}
          onMaterializePlan={() => onMaterializePlan(task)}
        />
      ))}
    </div>
  );
}