import { useState } from 'react';
import type { FormEvent } from 'react';
import { Plus } from 'lucide-react';
import type { AIAssistContext, CreateWorkitemInput } from '../../api';
import { AIAssistPanel } from '../common/AIAssistPanel';

type WorkitemCreateFormProps = {
  disabled: boolean;
  assistContext?: AIAssistContext;
  onCreate: (input: CreateWorkitemInput) => Promise<void>;
};

const workitemTypes = ['feature', 'bugfix', 'chore', 'research'];
const riskLevels = ['low', 'medium', 'high'];

export function WorkitemCreateForm({ disabled, assistContext = {}, onCreate }: WorkitemCreateFormProps) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [type, setType] = useState('feature');
  const [priority, setPriority] = useState(100);
  const [riskLevel, setRiskLevel] = useState('medium');
  const [requirements, setRequirements] = useState('');
  const [constraints, setConstraints] = useState('');
  const [acceptance, setAcceptance] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedTitle = title.trim();
    if (!trimmedTitle) return;
    try {
      await onCreate({
        title: trimmedTitle,
        type,
        requirements,
        constraints,
        acceptance: acceptance.split('\n').map((item) => item.trim()).filter(Boolean),
        priority,
        risk_level: riskLevel,
      });
    } catch {
      return;
    }
    setTitle('');
    setRequirements('');
    setConstraints('');
    setAcceptance('');
    setOpen(false);
  }

  if (!open) {
    return (
      <button className="secondary-button" disabled={disabled} onClick={() => setOpen(true)} title="Create workitem">
        <Plus size={15} />
        New Workitem
      </button>
    );
  }

  return (
    <form className="inline-form workitem-create-form" onSubmit={submit}>
      <AIAssistPanel
        target="workitem"
        draft={{ title, type, requirements, constraints, acceptance: acceptance.split('\n').filter(Boolean), priority, risk_level: riskLevel }}
        context={assistContext}
        disabled={disabled}
        onApplyDraft={(draft) => {
          if (typeof draft.title === 'string') setTitle(draft.title);
          if (typeof draft.type === 'string' && workitemTypes.includes(draft.type)) setType(draft.type);
          if (typeof draft.requirements === 'string') setRequirements(draft.requirements);
          if (typeof draft.constraints === 'string') setConstraints(draft.constraints);
          if (Array.isArray(draft.acceptance)) setAcceptance(draft.acceptance.filter((item) => typeof item === 'string').join('\n'));
          if (typeof draft.priority === 'number' && Number.isFinite(draft.priority)) setPriority(Math.max(0, Math.round(draft.priority)));
          if (typeof draft.risk_level === 'string' && riskLevels.includes(draft.risk_level)) setRiskLevel(draft.risk_level);
        }}
      />
      <label>
        <span>Title</span>
        <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Implement notes search" autoFocus />
      </label>
      <div className="form-grid-two">
        <label>
          <span>Type</span>
          <select value={type} onChange={(event) => setType(event.target.value)}>
            {workitemTypes.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label>
          <span>Risk</span>
          <select value={riskLevel} onChange={(event) => setRiskLevel(event.target.value)}>
            {riskLevels.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
      </div>
      <label>
        <span>Priority</span>
        <input type="number" min="0" value={priority} onChange={(event) => setPriority(Number(event.target.value))} />
      </label>
      <label>
        <span>Requirements</span>
        <textarea value={requirements} onChange={(event) => setRequirements(event.target.value)} rows={3} />
      </label>
      <label>
        <span>Constraints</span>
        <textarea value={constraints} onChange={(event) => setConstraints(event.target.value)} rows={2} />
      </label>
      <label>
        <span>Acceptance</span>
        <textarea value={acceptance} onChange={(event) => setAcceptance(event.target.value)} rows={3} placeholder="One criterion per line" />
      </label>
      <div className="form-actions">
        <button type="button" className="secondary-button" onClick={() => setOpen(false)} disabled={disabled}>Cancel</button>
        <button type="submit" className="primary-button" disabled={disabled || !title.trim()}>Create</button>
      </div>
    </form>
  );
}