import { useState } from 'react';
import { Check, ShieldCheck, X } from 'lucide-react';
import type { AIAssistContext, HumanAction } from '../../api';
import { AIAssistPanel } from '../common/AIAssistPanel';
import { StatusPill } from '../common/StatusPill';

type HumanActionMode = 'answer' | 'approve' | 'reject';

type ActiveHumanActionDialog = {
  action: HumanAction;
  mode: HumanActionMode;
};

type HumanActionListProps = {
  actions: HumanAction[];
  disabled: boolean;
  assistContext?: AIAssistContext;
  onAnswer: (action: HumanAction, text: string) => void;
  onApprove: (action: HumanAction, text: string) => void;
  onReject: (action: HumanAction, reason: string) => void;
};

export function HumanActionList({ actions, disabled, assistContext = {}, onAnswer, onApprove, onReject }: HumanActionListProps) {
  const [drafts, setDrafts] = useState<Record<string, { text?: string; reason?: string }>>({});
  const [activeDialog, setActiveDialog] = useState<ActiveHumanActionDialog | null>(null);
  const orderedActions = [...actions].sort(compareHumanActions);

  function selectOption(action: HumanAction, option: string) {
    const mode = action.kind === 'approval_request' ? 'approve' : 'answer';
    setDrafts((current) => ({ ...current, [action.id]: { ...current[action.id], text: responseTextForOption(action, option) } }));
    setActiveDialog({ action, mode });
  }

  if (!actions.length) {
    return <p className="empty-state">None</p>;
  }
  return (
    <div className="human-action-list">
      {orderedActions.map((action) => (
        <article className={`human-action human-action-${action.status.replaceAll('_', '-')}`} key={action.id}>
          <div className="human-action-main">
            <div className="human-action-heading">
              <StatusPill status={action.status} />
              <h4>{action.title}</h4>
            </div>
            <p className="human-action-meta">{action.kind} · {action.requested_by ?? 'unknown'} · {action.id}</p>
            {action.body && <p className="human-action-body">{action.body}</p>}
            {!!action.questions?.length && (
              <ol className="human-action-questions">
                {action.questions.map((question, index) => (
                  <li key={`${action.id}-question-${question.id ?? index}`}>{question.question ?? String(question)}</li>
                ))}
              </ol>
            )}
            {!!action.options?.length && (
              <div className="human-action-options" aria-label="Options">
                {action.options.map((option) => (
                  action.status === 'pending'
                    ? (
                        <button
                          key={`${action.id}-option-${option}`}
                          type="button"
                          className="human-action-option-button"
                          disabled={disabled}
                          onClick={() => selectOption(action, option)}
                        >
                          {option}
                        </button>
                      )
                    : <span key={`${action.id}-option-${option}`}>{option}</span>
                ))}
              </div>
            )}
            {!!action.evidence?.length && (
              <ul className="human-action-evidence" aria-label="Evidence">
                {action.evidence.map((item) => <li key={`${action.id}-evidence-${item}`}>{item}</li>)}
              </ul>
            )}
          </div>
          <div className="task-actions">
            <button title="Answer" disabled={disabled || action.status !== 'pending' || action.kind !== 'info_request'} onClick={() => setActiveDialog({ action, mode: 'answer' })}>
              <Check size={15} />
            </button>
            <button title="Approve" disabled={disabled || action.status !== 'pending' || action.kind !== 'approval_request'} onClick={() => setActiveDialog({ action, mode: 'approve' })}>
              <ShieldCheck size={15} />
            </button>
            <button title="Reject" disabled={disabled || action.status !== 'pending'} onClick={() => setActiveDialog({ action, mode: 'reject' })}>
              <X size={15} />
            </button>
          </div>
        </article>
      ))}
      {activeDialog && (
        <HumanActionResponseDialog
          action={activeDialog.action}
          mode={activeDialog.mode}
          draft={drafts[activeDialog.action.id] ?? {}}
          disabled={disabled}
          assistContext={assistContext}
          onDraftChange={(draft) => setDrafts((current) => ({ ...current, [activeDialog.action.id]: { ...current[activeDialog.action.id], ...draft } }))}
          onClose={() => setActiveDialog(null)}
          onSubmit={(value) => {
            if (activeDialog.mode === 'reject') onReject(activeDialog.action, value);
            else if (activeDialog.mode === 'approve') onApprove(activeDialog.action, value);
            else onAnswer(activeDialog.action, value);
            setActiveDialog(null);
          }}
        />
      )}
    </div>
  );
}

type HumanActionResponseDialogProps = {
  action: HumanAction;
  mode: HumanActionMode;
  draft: { text?: string; reason?: string };
  disabled: boolean;
  assistContext: AIAssistContext;
  onDraftChange: (draft: { text?: string; reason?: string }) => void;
  onClose: () => void;
  onSubmit: (value: string) => void;
};

function HumanActionResponseDialog({ action, mode, draft, disabled, assistContext, onDraftChange, onClose, onSubmit }: HumanActionResponseDialogProps) {
  const field = mode === 'reject' ? 'reason' : 'text';
  const value = draft[field] ?? '';
  const title = mode === 'reject' ? 'Reject Human Action' : mode === 'approve' ? 'Approve Human Action' : 'Answer Human Action';
  const label = mode === 'reject' ? 'Reason' : mode === 'approve' ? 'Approval note' : 'Answer';
  const actionContext = { ...assistContext, action_id: action.id, workitem_id: action.workitem_id, workflow_id: action.workflow_id, task_id: action.task_id };

  function fillFromOption(option: string) {
    const response = responseTextForOption(action, option);
    if (field === 'reason') onDraftChange({ reason: response });
    else onDraftChange({ text: response });
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="human-action-dialog" role="dialog" aria-modal="true" aria-label={title}>
        <header className="ai-assist-header">
          <span>{title}</span>
          <button type="button" className="secondary-button" disabled={disabled} onClick={onClose}>Cancel</button>
        </header>
        <div className="human-action-dialog-grid">
          <section className="human-action-request" aria-label="Request">
            <StatusPill status={action.status} />
            <h4>{action.title}</h4>
            <p className="human-action-meta">{action.kind} · {action.requested_by ?? 'unknown'} · {action.id}</p>
            {action.body && <p className="human-action-body">{action.body}</p>}
            {!!action.questions?.length && (
              <ol className="human-action-questions">
                {action.questions.map((question, index) => (
                  <li key={`${action.id}-dialog-question-${question.id ?? index}`}>{question.question ?? String(question)}</li>
                ))}
              </ol>
            )}
            {!!action.options?.length && (
              <div className="human-action-options" aria-label="Options">
                {action.options.map((option) => (
                  <button
                    key={`${action.id}-dialog-option-${option}`}
                    type="button"
                    className="human-action-option-button"
                    disabled={disabled || action.status !== 'pending'}
                    onClick={() => fillFromOption(option)}
                  >
                    {option}
                  </button>
                ))}
              </div>
            )}
          </section>
          <section className="human-action-response" aria-label="Response">
            <AIAssistPanel
              target="human_action"
              draft={{
                text: draft.text ?? '',
                reason: draft.reason ?? '',
                response_mode: mode,
                action_id: action.id,
                kind: action.kind,
                title: action.title,
                body: action.body,
                questions: action.questions,
                options: action.options,
                evidence: action.evidence,
              }}
              context={actionContext}
              disabled={disabled || action.status !== 'pending'}
              onApplyDraft={(nextDraft) => onDraftChange({
                text: typeof nextDraft.text === 'string' ? nextDraft.text : draft.text,
                reason: typeof nextDraft.reason === 'string' ? nextDraft.reason : draft.reason,
              })}
            />
            <label>
              <span>{label}</span>
              <textarea rows={10} value={value} onChange={(event) => onDraftChange({ [field]: event.target.value })} autoFocus />
            </label>
          </section>
        </div>
        <div className="form-actions">
          <button type="button" className="secondary-button" disabled={disabled} onClick={onClose}>Cancel</button>
          <button type="button" className="primary-button" disabled={disabled || !value.trim()} onClick={() => onSubmit(value.trim())}>{mode === 'reject' ? 'Reject' : mode === 'approve' ? 'Approve' : 'Submit Answer'}</button>
        </div>
      </section>
    </div>
  );
}

function compareHumanActions(left: HumanAction, right: HumanAction): number {
  const pendingDelta = actionPriority(left) - actionPriority(right);
  if (pendingDelta !== 0) return pendingDelta;
  return actionTime(right) - actionTime(left);
}

function actionPriority(action: HumanAction): number {
  return action.status === 'pending' ? 0 : 1;
}

function actionTime(action: HumanAction): number {
  const timestamp = action.status === 'pending' ? action.created_at : action.resolved_at ?? action.created_at;
  return timestamp ? Date.parse(timestamp) || 0 : 0;
}

function responseTextForOption(action: HumanAction, option: string): string {
  if (!isDefaultOption(option)) return option;
  const defaultDetails = defaultDetailsFromBody(action.body ?? '');
  if (!defaultDetails) return option;
  return `${option}：${defaultDetails}`;
}

function isDefaultOption(option: string): boolean {
  const normalized = option.toLowerCase();
  return normalized.includes('default') || normalized.includes('accept') || option.includes('默认') || option.includes('接受') || option.includes('建议');
}

function defaultDetailsFromBody(body: string): string {
  const markerMatch = body.match(/默认建议[:：]\s*([\s\S]+)/);
  if (!markerMatch) return '';
  return markerMatch[1].trim();
}