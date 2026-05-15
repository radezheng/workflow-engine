import type { Task } from '../api';

export function summarizeTasks(tasks: Task[]) {
  return tasks.reduce(
    (summary, task) => {
      if (task.status === 'ready') summary.ready += 1;
      if (task.status === 'running') summary.running += 1;
      if (task.status.startsWith('waiting')) summary.waiting += 1;
      if (['failed', 'cancelled'].includes(task.status)) summary.failed += 1;
      if (['succeeded', 'skipped', 'superseded'].includes(task.status)) summary.done += 1;
      return summary;
    },
    { ready: 0, running: 0, waiting: 0, failed: 0, done: 0 },
  );
}