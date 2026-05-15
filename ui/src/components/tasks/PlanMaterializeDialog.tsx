import { useState } from 'react';
import { FileText, ListPlus, X } from 'lucide-react';
import type { PromptTemplate, Task } from '../../api';
import { MarkdownPreview } from '../common/MarkdownPreview';

type PlanMaterializeDialogProps = {
  task: Task | null;
  templates: PromptTemplate[];
  promptTemplateRef: string;
  promptText: string;
  disabled: boolean;
  onPromptTemplateRefChange: (value: string) => void;
  onPromptTextChange: (value: string) => void;
  onClose: () => void;
  onSubmit: () => void;
};

export function PlanMaterializeDialog({
  task,
  templates,
  promptTemplateRef,
  promptText,
  disabled,
  onPromptTemplateRefChange,
  onPromptTextChange,
  onClose,
  onSubmit,
}: PlanMaterializeDialogProps) {
  const [mode, setMode] = useState<'edit' | 'preview'>('edit');
  const [selectedTemplateKey, setSelectedTemplateKey] = useState('');
  if (!task) return null;
  const [fallbackRole, fallbackName] = promptTemplateRef.split('/');
  const fallbackTemplate: PromptTemplate = {
    id: `workflow-action:${promptTemplateRef}`,
    source: 'public',
    role: fallbackRole || 'workflow',
    name: fallbackName || 'materialize',
    version: 'file',
    description: '',
    body_md: '',
    tags: [],
    path: '',
    updated_at: 0,
  };
  const options = templates
    .filter((template) => template.role === 'designer' || template.role === 'planner')
    .sort((left, right) => `${left.role}/${left.name}/${left.source}`.localeCompare(`${right.role}/${right.name}/${right.source}`));
  const displayOptions = options.some((template) => `${template.role}/${template.name}` === promptTemplateRef)
    ? options
    : [fallbackTemplate, ...options];
  const templateKey = (template: PromptTemplate) => `${template.source}:${template.role}/${template.name}:${template.path}`;
  const selectedTemplate = displayOptions.find((template) => templateKey(template) === selectedTemplateKey && `${template.role}/${template.name}` === promptTemplateRef)
    ?? displayOptions.find((template) => `${template.role}/${template.name}` === promptTemplateRef)
    ?? fallbackTemplate;
  const promptBody = selectedTemplate.body_md || '_Prompt template body is not loaded in the browser yet; the backend will resolve this template when the task runs._';

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="prompt-picker-modal" role="dialog" aria-modal="true" aria-label="Break down plan">
        <div className="ai-assist-header">
          <span><ListPlus size={15} /> Break Down Plan</span>
          <button type="button" className="secondary-button" disabled={disabled} onClick={onClose}>
            <X size={15} />
            Close
          </button>
        </div>
        <div className="prompt-picker-grid">
          <div className="prompt-picker-list" aria-label="Prompt templates">
            {displayOptions.map((template) => {
              const ref = `${template.role}/${template.name}`;
              const key = templateKey(template);
              return (
                <button
                  key={key}
                  type="button"
                  className={key === templateKey(selectedTemplate) ? 'template-button selected' : 'template-button'}
                  disabled={disabled}
                  onClick={() => {
                    setSelectedTemplateKey(key);
                    onPromptTemplateRefChange(ref);
                  }}
                >
                  <span>{ref}</span>
                  <small>{template.source}{template.path ? ` · ${template.path}` : ''}</small>
                </button>
              );
            })}
          </div>
          <div className="prompt-picker-detail">
            <div className="plan-breakdown-toolbar">
              <div className="plan-breakdown-selection">
                <span>Prompt</span>
                <strong>{promptTemplateRef}</strong>
                <small>{selectedTemplate.source}{selectedTemplate.path ? ` · ${selectedTemplate.path}` : ''}</small>
              </div>
              <div className="stream-tabs" aria-label="Prompt mode">
                <button type="button" className={mode === 'edit' ? 'selected' : ''} disabled={disabled} onClick={() => setMode('edit')}>Edit</button>
                <button type="button" className={mode === 'preview' ? 'selected' : ''} disabled={disabled} onClick={() => setMode('preview')}>Preview</button>
              </div>
            </div>
            <div className="plan-breakdown-sections">
              <div className="plan-breakdown-section">
                <div className="plan-breakdown-section-title">Prompt Preview</div>
                <div className="plan-breakdown-preview prompt-body" aria-label="Prompt template preview">
                  <MarkdownPreview text={promptBody} emptyText="No prompt template body available" />
                </div>
              </div>
              <div className="plan-breakdown-section">
                <div className="plan-breakdown-section-title">Input Override</div>
                {mode === 'edit' ? (
                  <textarea className="plan-breakdown-input" value={promptText} onChange={(event) => onPromptTextChange(event.target.value)} rows={12} disabled={disabled} placeholder="Optional. Leave empty to let the backend render input from the workflow template." />
                ) : (
                  <div className="plan-breakdown-preview input-body" aria-label="Input preview">
                    <MarkdownPreview text={promptText} emptyText="Backend will render the input from the workflow template." />
                  </div>
                )}
              </div>
            </div>
            <div className="form-actions">
              <button type="button" className="secondary-button" disabled={disabled} onClick={onClose}>Cancel</button>
              <button type="button" className="primary-button" disabled={disabled || !promptTemplateRef.trim()} onClick={onSubmit}>
                <FileText size={15} />
                Create Breakdown Task
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
