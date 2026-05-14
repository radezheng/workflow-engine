import { useMemo, useState } from 'react';
import { Check, FileText, Save, Trash2, X } from 'lucide-react';
import type { PromptTemplate } from '../../api';
import { MarkdownPreview } from '../common/MarkdownPreview';

type PromptTemplatePickerProps = {
  open: boolean;
  title: string;
  templates: PromptTemplate[];
  selectedRef: string;
  disabled: boolean;
  roleFilter?: string;
  onClose: () => void;
  onSelect: (promptTemplateRef: string) => void;
  onSaveProject: (input: { role: string; name: string; body: string }) => Promise<PromptTemplate | void>;
  onSavePublic: (input: { role: string; name: string; body: string }) => Promise<PromptTemplate | void>;
  onDelete: (template: PromptTemplate) => Promise<void>;
};

export function PromptTemplatePicker({
  open,
  title,
  templates,
  selectedRef,
  disabled,
  roleFilter,
  onClose,
  onSelect,
  onSaveProject,
  onSavePublic,
  onDelete,
}: PromptTemplatePickerProps) {
  const visibleTemplates = useMemo(() => {
    const filtered = roleFilter ? templates.filter((template) => template.role === roleFilter) : templates;
    return filtered.slice().sort((left, right) => `${left.role}/${left.name}/${left.source}`.localeCompare(`${right.role}/${right.name}/${right.source}`));
  }, [roleFilter, templates]);
  const selectedTemplate = visibleTemplates.find((template) => `${template.role}/${template.name}` === selectedRef)
    ?? visibleTemplates[0]
    ?? null;
  const [activeId, setActiveId] = useState('');
  const activeTemplate = visibleTemplates.find((template) => template.id === activeId) ?? selectedTemplate;
  const [role, setRole] = useState('');
  const [name, setName] = useState('');
  const [body, setBody] = useState('');
  const [savePublic, setSavePublic] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  if (!open) return null;

  const currentRole = role || activeTemplate?.role || roleFilter || 'planner';
  const currentName = name || activeTemplate?.name || 'workitem-plan';
  const currentBody = body || activeTemplate?.body_md || '';
  const currentRef = `${currentRole}/${currentName}`;

  function loadTemplate(template: PromptTemplate) {
    setActiveId(template.id);
    setRole(template.role);
    setName(template.name);
    setBody(template.body_md);
    setError('');
  }

  async function save() {
    const nextRole = currentRole.trim();
    const nextName = currentName.trim().replace(/\.md$/, '');
    if (!nextRole || !nextName || !currentBody.trim()) return;
    setBusy(true);
    setError('');
    try {
      await onSaveProject({ role: nextRole, name: nextName, body: currentBody });
      if (savePublic) {
        await onSavePublic({ role: nextRole, name: nextName, body: currentBody });
      }
      onSelect(`${nextRole}/${nextName}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!activeTemplate) return;
    const confirmed = window.confirm(`Delete ${activeTemplate.source} prompt ${activeTemplate.role}/${activeTemplate.name}?`);
    if (!confirmed) return;
    setBusy(true);
    setError('');
    try {
      await onDelete(activeTemplate);
      setActiveId('');
      setRole('');
      setName('');
      setBody('');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="prompt-picker-modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="ai-assist-header">
          <span><FileText size={15} /> {title}</span>
          <button type="button" className="secondary-button" disabled={busy} onClick={onClose}>
            <X size={15} />
            Close
          </button>
        </div>
        <div className="prompt-picker-grid">
          <div className="prompt-picker-list" aria-label="Prompt templates">
            {!visibleTemplates.length && <p className="empty-state">No prompt templates</p>}
            {visibleTemplates.map((template) => {
              const ref = `${template.role}/${template.name}`;
              return (
                <button
                  key={template.id}
                  type="button"
                  className={template.id === activeTemplate?.id ? 'template-button selected' : 'template-button'}
                  onClick={() => loadTemplate(template)}
                >
                  <span>{ref}</span>
                  <small>{template.source} · {template.path}</small>
                  {ref === selectedRef && <small>Current</small>}
                </button>
              );
            })}
          </div>
          <div className="prompt-picker-detail">
            <div className="form-grid-two">
              <label>
                <span>Role</span>
                <input value={currentRole} onChange={(event) => setRole(event.target.value)} disabled={busy || disabled || Boolean(roleFilter)} />
              </label>
              <label>
                <span>Name</span>
                <input value={currentName} onChange={(event) => setName(event.target.value)} disabled={busy || disabled} />
              </label>
            </div>
            <div className="prompt-preview-pane" aria-label="Rendered prompt preview">
              <MarkdownPreview text={currentBody} emptyText="No prompt template content" />
            </div>
            <label className="prompt-source-editor">
              <span>Edit Markdown</span>
              <textarea value={currentBody} onChange={(event) => setBody(event.target.value)} rows={10} disabled={busy || disabled} />
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={savePublic} onChange={(event) => setSavePublic(event.target.checked)} disabled={busy || disabled} />
              <span>Also save to public library</span>
            </label>
            {error && <div className="inline-error" role="status">{error}</div>}
            <div className="template-actions">
              <button type="button" className="secondary-button" disabled={busy || disabled || !activeTemplate} onClick={remove}>
                <Trash2 size={15} />
                Delete
              </button>
              <button type="button" className="secondary-button" disabled={busy || disabled || !currentRef} onClick={() => onSelect(currentRef)}>
                <Check size={15} />
                Use Prompt
              </button>
              <button type="button" className="primary-button" disabled={busy || disabled || !currentRole.trim() || !currentName.trim() || !currentBody.trim()} onClick={() => void save()}>
                <Save size={15} />
                Save to Project
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
