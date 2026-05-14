import { useState } from 'react';
import { ClipboardList, FileText } from 'lucide-react';
import type { PromptTemplate, Workitem } from '../../api';
import { PromptTemplatePicker } from '../prompt-templates/PromptTemplatePicker';

type WorkitemListProps = {
  workitems: Workitem[];
  selectedWorkitem: Workitem | null;
  plannerTemplates: PromptTemplate[];
  disabled: boolean;
  onSelectWorkitem: (workitem: Workitem) => void;
  onPlanWorkitem: (workitem: Workitem, promptTemplateRef: string) => void;
  onSavePromptToProject: (input: { role: string; name: string; body: string }) => Promise<PromptTemplate | void>;
  onSavePromptToPublic: (input: { role: string; name: string; body: string }) => Promise<PromptTemplate | void>;
  onDeletePrompt: (template: PromptTemplate) => Promise<void>;
};

export function WorkitemList({ workitems, selectedWorkitem, plannerTemplates, disabled, onSelectWorkitem, onPlanWorkitem, onSavePromptToProject, onSavePromptToPublic, onDeletePrompt }: WorkitemListProps) {
  const [planPromptsByWorkitem, setPlanPromptsByWorkitem] = useState<Record<string, string>>({});
  const [pickerWorkitem, setPickerWorkitem] = useState<Workitem | null>(null);
  if (!workitems.length) {
    return <p className="empty-state">No workitems</p>;
  }
  const fallbackTemplate: PromptTemplate = {
    id: 'default:planner/workitem-plan',
    source: 'public',
    role: 'planner',
    name: 'workitem-plan',
    version: 'file',
    description: '',
    body_md: '',
    tags: [],
    path: '',
    updated_at: 0,
  };
  const templateOptions = plannerTemplates.length ? plannerTemplates : [fallbackTemplate];
  const orderedWorkitems = [...workitems].sort(compareWorkitemsByNewestFirst);
  return (
    <div className="workitem-list">
      {orderedWorkitems.map((item, index) => (
        <article key={item.id} className={item.id === selectedWorkitem?.id ? 'workitem selected' : 'workitem'}>
          <button type="button" className="workitem-main" onClick={() => onSelectWorkitem(item)} title="Open workitem">
            <span className="workitem-title-row">
              <span className="workitem-number">{index + 1}</span>
              <span>{item.title}</span>
            </span>
            <small>{item.status} · p{item.priority} · {item.risk_level}</small>
          </button>
          <div className="workitem-plan-actions">
            <button
              type="button"
              className="secondary-button prompt-ref-button"
              disabled={disabled}
              onClick={(event) => {
                event.stopPropagation();
                setPickerWorkitem(item);
              }}
              title="Choose plan prompt"
            >
              <FileText size={15} />
              {planPromptsByWorkitem[item.id] ?? 'planner/workitem-plan'}
            </button>
            <button
              type="button"
              className="secondary-button"
              disabled={disabled}
              onClick={(event) => {
                event.stopPropagation();
                onPlanWorkitem(item, planPromptsByWorkitem[item.id] ?? 'planner/workitem-plan');
              }}
              title="Create workflow and planner task"
            >
              <ClipboardList size={15} />
              Plan
            </button>
          </div>
        </article>
      ))}
      {pickerWorkitem && (
        <PromptTemplatePicker
          open={Boolean(pickerWorkitem)}
          title="Choose Plan Prompt"
          templates={templateOptions}
          roleFilter="planner"
          selectedRef={planPromptsByWorkitem[pickerWorkitem.id] ?? 'planner/workitem-plan'}
          disabled={disabled}
          onClose={() => setPickerWorkitem(null)}
          onSelect={(promptTemplateRef) => {
            setPlanPromptsByWorkitem((current) => ({ ...current, [pickerWorkitem.id]: promptTemplateRef }));
            setPickerWorkitem(null);
          }}
          onSaveProject={onSavePromptToProject}
          onSavePublic={onSavePromptToPublic}
          onDelete={onDeletePrompt}
        />
      )}
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