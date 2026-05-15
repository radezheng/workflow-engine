import { useState } from 'react';
import { Archive, ClipboardList, Ellipsis, RotateCcw } from 'lucide-react';
import type { Workitem, WorkflowTemplate } from '../../api';

type WorkitemListProps = {
  workitems: Workitem[];
  selectedWorkitem: Workitem | null;
  workflowTemplates: WorkflowTemplate[];
  disabled: boolean;
  showArchived: boolean;
  onSelectWorkitem: (workitem: Workitem) => void;
  onPlanWorkitem: (workitem: Workitem, workflowTemplateId: string, parameters: Record<string, string>) => void;
  onArchiveWorkitem: (workitem: Workitem) => void;
  onRestoreWorkitem: (workitem: Workitem) => void;
  onShowArchivedChange: (showArchived: boolean) => void;
};

export function WorkitemList({ workitems, selectedWorkitem, workflowTemplates, disabled, showArchived, onSelectWorkitem, onPlanWorkitem, onArchiveWorkitem, onRestoreWorkitem, onShowArchivedChange }: WorkitemListProps) {
  const [templatesByWorkitem, setTemplatesByWorkitem] = useState<Record<string, string>>({});
  const [openWorkitemId, setOpenWorkitemId] = useState<string | null>(null);
  if (!workitems.length) {
    return <><label className="toggle-row compact"><input type="checkbox" checked={showArchived} onChange={(event) => onShowArchivedChange(event.target.checked)} />Show archived</label><p className="empty-state">No workitems</p></>;
  }
  const templateOptions = workflowTemplates.length ? workflowTemplates : [{ id: 'software-project-dev', name: 'Software Project Development', resolved_parameters: {} } as WorkflowTemplate];
  const orderedWorkitems = [...workitems].sort(compareWorkitemsByNewestFirst);
  return (
    <div className="workitem-list">
      <label className="toggle-row compact"><input type="checkbox" checked={showArchived} onChange={(event) => onShowArchivedChange(event.target.checked)} />Show archived</label>
      {orderedWorkitems.map((item, index) => {
          const archived = item.status === 'archived';
          const planDisabled = disabled || archived;
          return (
            <article key={item.id} className={item.id === selectedWorkitem?.id ? 'workitem selected' : 'workitem'}>
              <div className="workitem-header-row">
                <button type="button" className="workitem-main" onClick={() => onSelectWorkitem(item)} title="Open workitem">
                  <span className="workitem-title-row">
                    <span className="workitem-number">{index + 1}</span>
                    <span>{item.title}</span>
                  </span>
                  <small>{item.status} · p{item.priority} · {item.risk_level}</small>
                </button>
                <div className="row-menu">
                  <button type="button" className="icon-button" onClick={() => setOpenWorkitemId(openWorkitemId === item.id ? null : item.id)} title="Workitem actions" aria-label={`Actions for ${item.title}`}>
                    <Ellipsis size={16} />
                  </button>
                  {openWorkitemId === item.id && (
                    <div className="row-menu-popover" role="menu">
                      {archived ? (
                        <button type="button" role="menuitem" disabled={disabled} onClick={() => { setOpenWorkitemId(null); onRestoreWorkitem(item); }}>
                          <RotateCcw size={14} />
                          Restore
                        </button>
                      ) : (
                        <button type="button" role="menuitem" disabled={disabled} onClick={() => { setOpenWorkitemId(null); onArchiveWorkitem(item); }}>
                          <Archive size={14} />
                          Archive
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>
              <div className="workitem-plan-actions">
                <select
                  className="prompt-ref-button"
                  disabled={planDisabled}
                  value={templatesByWorkitem[item.id] ?? templateOptions[0]?.id ?? 'software-project-dev'}
                  onClick={(event) => event.stopPropagation()}
                  onChange={(event) => setTemplatesByWorkitem((current) => ({ ...current, [item.id]: event.target.value }))}
                  title="Choose workflow template"
                >
                  {templateOptions.map((template) => (
                    <option key={template.id} value={template.id}>{template.name || template.id}</option>
                  ))}
                </select>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={planDisabled}
                  onClick={(event) => {
                    event.stopPropagation();
                    const workflowTemplateId = templatesByWorkitem[item.id] ?? templateOptions[0]?.id ?? 'software-project-dev';
                    const template = templateOptions.find((option) => option.id === workflowTemplateId);
                    onPlanWorkitem(item, workflowTemplateId, template?.resolved_parameters ?? {});
                  }}
                  title="Create workflow from template"
                >
                  <ClipboardList size={15} />
                  Plan
                </button>
              </div>
            </article>
          );
        })}
    </div>
  );
}

function compareWorkitemsByNewestFirst(left: Workitem, right: Workitem) {
  const byCreatedAt = Date.parse(right.created_at) - Date.parse(left.created_at);
  if (Number.isFinite(byCreatedAt) && byCreatedAt !== 0) {
    return byCreatedAt;
  }
  return right.id.localeCompare(left.id);
}