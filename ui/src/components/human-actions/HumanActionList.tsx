import { useState } from 'react';
import { Check, ShieldCheck, X } from 'lucide-react';
import type { HumanAction } from '../../api';
import { AIAssistPanel } from '../common/AIAssistPanel';
import { StatusPill } from '../common/StatusPill';

type HumanActionListProps = {
  actions: HumanAction[];
  disabled: boolean;
  onAnswer: (action: HumanAction, text: string) => void;
  onApprove: (action: HumanAction, text: string) => void;
  onReject: (action: HumanAction, reason: string) => void;
};

export function HumanActionList({ actions, disabled, onAnswer, onApprove, onReject }: HumanActionListProps) {
  const [drafts, setDrafts] = useState<Record<string, { text?: string; reason?: string }>>({});

  if (!actions.length) {
    return <p className="empty-state">None</p>;
  }
  return (
    <div className="human-action-list">
      {actions.map((action) => (
        <article className="human-action" key={action.id}>
          <div>
            <StatusPill status={action.status} />
            <h4>{action.title}</h4>
            <p>{action.kind} · {action.requested_by ?? 'unknown'}</p>
            <AIAssistPanel
              target="human_action"
              draft={{
                text: drafts[action.id]?.text ?? '',
                reason: drafts[action.id]?.reason ?? '',
                kind: action.kind,
                title: action.title,
                body: action.body,
              }}
              disabled={disabled || action.status !== 'pending'}
              onApplyDraft={(draft) => setDrafts((current) => ({
                ...current,
                [action.id]: {
                  text: typeof draft.text === 'string' ? draft.text : current[action.id]?.text,
                  reason: typeof draft.reason === 'string' ? draft.reason : current[action.id]?.reason,
                },
              }))}
            />
          </div>
          <div className="task-actions">
            <button title="Answer" disabled={disabled || action.status !== 'pending' || action.kind !== 'info_request'} onClick={() => onAnswer(action, window.prompt('Answer', drafts[action.id]?.text ?? '') ?? '')}>
              <Check size={15} />
            </button>
            <button title="Approve" disabled={disabled || action.status !== 'pending' || action.kind !== 'approval_request'} onClick={() => onApprove(action, window.prompt('Approval note', drafts[action.id]?.text ?? '') ?? '')}>
              <ShieldCheck size={15} />
            </button>
            <button title="Reject" disabled={disabled || action.status !== 'pending'} onClick={() => onReject(action, window.prompt('Reason', drafts[action.id]?.reason ?? 'Rejected from UI') ?? 'Rejected from UI')}>
              <X size={15} />
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}