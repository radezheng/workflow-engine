import { Play } from 'lucide-react';
import type { ProjectRecord, Workitem } from '../../api';

type TopbarProps = {
  selectedProject: ProjectRecord | null;
  selectedWorkitem: Workitem | null;
  disabled: boolean;
  running: boolean;
  autoRun: boolean;
  autoDisabled: boolean;
  onRunNext: () => void;
  onAutoRunChange: (checked: boolean) => void;
};

export function Topbar({ selectedProject, selectedWorkitem, disabled, running, autoRun, autoDisabled, onRunNext, onAutoRunChange }: TopbarProps) {
  return (
    <header className="topbar">
      <div>
        <span className="eyebrow">{selectedProject?.root_path ?? 'No project selected'}</span>
        <h2>{selectedWorkitem?.title ?? 'Workitems'}</h2>
      </div>
      <div className="topbar-actions">
        <label className="auto-run-toggle" title="Keep running ready tasks until blocked, failed, or waiting for human input">
          <input type="checkbox" checked={autoRun} disabled={autoDisabled} onChange={(event) => onAutoRunChange(event.target.checked)} />
          <span>Auto</span>
        </label>
        <button className="primary-button" disabled={disabled} onClick={onRunNext} title="Run next ready task">
          <Play size={16} />
          {running ? 'Running...' : 'Run Next'}
        </button>
      </div>
    </header>
  );
}