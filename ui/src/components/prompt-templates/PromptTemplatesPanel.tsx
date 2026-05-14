import { useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { FileText, Plus, Upload } from 'lucide-react';
import type { CreatePromptTemplateInput, ProjectRecord, PromptTemplate } from '../../api';
import { createPromptTemplate, getPromptTemplates, getPublicPromptTemplates, publishPromptTemplate } from '../../api';
import { AIAssistPanel } from '../common/AIAssistPanel';
import { PanelTitle } from '../common/PanelTitle';

type PromptTemplatesPanelProps = {
  project: ProjectRecord | null;
  refreshToken: number;
  disabled: boolean;
  onError: (message: string) => void;
};

export function PromptTemplatesPanel({ project, refreshToken, disabled, onError }: PromptTemplatesPanelProps) {
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [busy, setBusy] = useState(false);
  const selected = useMemo(() => templates.find((template) => template.id === selectedId) ?? templates[0] ?? null, [templates, selectedId]);

  async function refresh(isCurrent: () => boolean = () => true) {
    if (!project) {
      if (!isCurrent()) return;
      const payload = await getPublicPromptTemplates();
      if (!isCurrent()) return;
      setTemplates(payload);
      setSelectedId((current) => current && payload.some((template) => template.id === current) ? current : payload[0]?.id ?? '');
      return;
    }
    const payload = await getPromptTemplates(project.project_ref, project.id);
    if (!isCurrent()) return;
    setTemplates(payload);
    setSelectedId((current) => current && payload.some((template) => template.id === current) ? current : payload[0]?.id ?? '');
  }

  useEffect(() => {
    let active = true;
    void refresh(() => active).catch((caught) => {
      if (active) onError(caught instanceof Error ? caught.message : String(caught));
    });
    return () => { active = false; };
  }, [project, refreshToken]);

  async function handleCreate(input: CreatePromptTemplateInput) {
    if (!project) return;
    setBusy(true);
    try {
      const created = await createPromptTemplate(project.project_ref, project.id, input);
      await refresh();
      setSelectedId(created.id);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : String(caught));
      throw caught;
    } finally {
      setBusy(false);
    }
  }

  async function handlePublish(template: PromptTemplate) {
    setBusy(true);
    try {
      const published = await publishPromptTemplate({
        role: template.role,
        name: template.name,
        version: 'file',
        description: template.description,
        tags: template.tags,
        body: template.body_md,
      });
      await refresh();
      setSelectedId(published.id);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveToProject(template: PromptTemplate) {
    if (!project) return;
    setBusy(true);
    try {
      const saved = await createPromptTemplate(project.project_ref, project.id, {
        role: template.role,
        name: template.name,
        version: 'file',
        description: template.description,
        tags: template.tags,
        body: template.body_md,
      });
      await refresh();
      setSelectedId(saved.id);
    } catch (caught) {
      onError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="template-grid">
      <section className="panel template-list-panel" aria-label="Prompt templates">
        <PanelTitle icon={<FileText size={17} />} title="Prompt Templates" />
        <PromptTemplateCreateForm disabled={disabled || busy || !project} onCreate={handleCreate} />
        <div className="template-list">
          {!templates.length && <p className="empty-state">No prompt templates</p>}
          {templates.map((template) => (
            <button
              key={template.id}
              className={template.id === selected?.id ? 'template-button selected' : 'template-button'}
              onClick={() => setSelectedId(template.id)}
            >
              <span>{template.role}/{template.name}</span>
              <small>{template.source} · {template.path}</small>
            </button>
          ))}
        </div>
      </section>

      <section className="panel template-detail-panel" aria-label="Prompt template detail">
        {selected ? (
          <div className="template-detail">
            <div className="detail-header">
              <div>
                <h4>{selected.role}/{selected.name}</h4>
                <p>{selected.source} template</p>
              </div>
              <span>{selected.version}</span>
            </div>
            <p className="template-path">{selected.path}</p>
            <div className="template-actions">
              <button type="button" className="secondary-button" disabled={busy || disabled || !project} onClick={() => void handleSaveToProject(selected)}>
                <FileText size={15} />
                Save to Project
              </button>
              <button type="button" className="secondary-button" disabled={busy} onClick={() => void handlePublish(selected)}>
                <Upload size={15} />
                Push Public
              </button>
            </div>
            <pre className="log-viewer">{selected.body_md}</pre>
          </div>
        ) : (
          <p className="empty-state">Select a prompt template</p>
        )}
      </section>
    </div>
  );
}

function PromptTemplateCreateForm({ disabled, onCreate }: { disabled: boolean; onCreate: (input: CreatePromptTemplateInput) => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState('reviewer');
  const [name, setName] = useState('implementation-review');
  const [body, setBody] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!role.trim() || !name.trim()) return;
    try {
      await onCreate({
        role: role.trim(),
        name: name.trim(),
        version: 'file',
        description: '',
        tags: [],
        body: body.trim() || undefined,
      });
    } catch {
      return;
    }
    setBody('');
    setOpen(false);
  }

  if (!open) {
    return (
      <button type="button" className="secondary-button" disabled={disabled} onClick={() => setOpen(true)} title="Create prompt template">
        <Plus size={15} />
        New Template
      </button>
    );
  }

  return (
    <form className="inline-form" onSubmit={submit}>
      <AIAssistPanel
        target="prompt_template"
        draft={{ role, name, body }}
        disabled={disabled}
        onApplyDraft={(draft) => {
          if (typeof draft.role === 'string') setRole(draft.role);
          if (typeof draft.name === 'string') setName(draft.name);
          if (typeof draft.body === 'string') setBody(draft.body);
        }}
      />
      <div className="form-grid-two">
        <label>
          <span>Role</span>
          <input value={role} onChange={(event) => setRole(event.target.value)} autoFocus />
        </label>
        <label>
          <span>Name</span>
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
      </div>
      <label>
        <span>Body</span>
        <textarea value={body} onChange={(event) => setBody(event.target.value)} rows={8} placeholder="Leave empty to copy the public template with the same role/name" />
      </label>
      <div className="form-actions">
        <button type="button" className="secondary-button" onClick={() => setOpen(false)} disabled={disabled}>Cancel</button>
        <button type="submit" className="primary-button" disabled={disabled || !role.trim() || !name.trim()}>Create</button>
      </div>
    </form>
  );
}