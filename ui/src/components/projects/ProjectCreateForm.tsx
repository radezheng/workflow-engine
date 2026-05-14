import { useState } from 'react';
import type { FormEvent } from 'react';
import { Plus } from 'lucide-react';
import type { CreateProjectInput } from '../../api';
import { AIAssistPanel } from '../common/AIAssistPanel';

type ProjectCreateFormProps = {
  disabled: boolean;
  onCreate: (input: CreateProjectInput) => Promise<void>;
};

export function ProjectCreateForm({ disabled, onCreate }: ProjectCreateFormProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [projectRef, setProjectRef] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) return;
    try {
      await onCreate({ name: trimmedName, project_ref: projectRef.trim() || undefined });
    } catch {
      return;
    }
    setName('');
    setProjectRef('');
    setOpen(false);
  }

  if (!open) {
    return (
      <button className="secondary-button" disabled={disabled} onClick={() => setOpen(true)} title="Create project">
        <Plus size={15} />
        New Project
      </button>
    );
  }

  return (
    <form className="inline-form" onSubmit={submit}>
      <AIAssistPanel
        target="project"
        draft={{ name, project_ref: projectRef }}
        disabled={disabled}
        onApplyDraft={(draft) => {
          if (typeof draft.name === 'string') setName(draft.name);
          if (typeof draft.project_ref === 'string') setProjectRef(draft.project_ref);
        }}
      />
      <label>
        <span>Name</span>
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="notes-app" autoFocus />
      </label>
      <label>
        <span>Folder</span>
        <input value={projectRef} onChange={(event) => setProjectRef(event.target.value)} placeholder="optional-project-ref" />
      </label>
      <div className="form-actions">
        <button type="button" className="secondary-button" onClick={() => setOpen(false)} disabled={disabled}>Cancel</button>
        <button type="submit" className="primary-button" disabled={disabled || !name.trim()}>Create</button>
      </div>
    </form>
  );
}