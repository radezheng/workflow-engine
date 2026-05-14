import type { ProjectEvent } from '../../api';

function eventSummary(event: ProjectEvent) {
  const payload = event.payload;
  const parts: string[] = [];
  const runId = event.run_id ?? payload.run_id;
  if (runId) parts.push(`run_id=${String(runId)}`);
  for (const key of ['tasks_started', 'tasks_succeeded', 'tasks_failed', 'waiting_for_human', 'status', 'exit_code', 'reason']) {
    if (payload[key] !== undefined && payload[key] !== null) parts.push(`${key}=${String(payload[key])}`);
  }
  for (const key of ['blocked', 'failed', 'open']) {
    const value = payload[key];
    if (Array.isArray(value) && value.length) parts.push(`${key}=${value.length}`);
  }
  return parts.join(' · ');
}

export function EventList({ events, emptyText = 'None' }: { events: ProjectEvent[]; emptyText?: string }) {
  if (!events.length) {
    return <p className="empty-state">{emptyText}</p>;
  }
  return (
    <div className="event-list">
      {events.slice().reverse().map((event) => (
        <article className="event-row" key={event.id}>
          <span>
            {event.type}
            {eventSummary(event) && <small>{eventSummary(event)}</small>}
          </span>
          <small>{event.created_at}</small>
        </article>
      ))}
    </div>
  );
}