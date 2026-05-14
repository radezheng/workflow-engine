import { CircleDot, FileText, GitBranch, ListChecks, RefreshCw, Settings, SquareStack, TerminalSquare } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { ProjectRecord } from '../../api';
import type { CreateProjectInput } from '../../api';
import { PlaceholderMenuItem } from '../navigation/PlaceholderMenuItem';
import { ProjectCreateForm } from '../projects/ProjectCreateForm';
import { ProjectList } from '../projects/ProjectList';

type LoadState = 'idle' | 'loading' | 'ready' | 'error';

type SidebarProps = {
  projects: ProjectRecord[];
  selectedProject: ProjectRecord | null;
  activeView: ConsoleView;
  loadState: LoadState;
  busy: boolean;
  showArchived: boolean;
  onRefresh: () => void;
  onCreateProject: (input: CreateProjectInput) => Promise<void>;
  onSelectProject: (project: ProjectRecord) => void;
  onArchiveProject: (project: ProjectRecord) => void;
  onRestoreProject: (project: ProjectRecord) => void;
  onShowArchivedChange: (showArchived: boolean) => void;
  onViewChange: (view: ConsoleView) => void;
};

export type ConsoleView = 'workflow' | 'prompt-templates' | 'settings';

const activeMenuItems: { view: ConsoleView; label: string; icon: LucideIcon }[] = [
  { view: 'workflow', label: 'Workflow', icon: ListChecks },
  { view: 'prompt-templates', label: 'Prompt Templates', icon: FileText },
  { view: 'settings', label: 'Settings', icon: Settings },
];

const plannedMenuItems: { label: string; icon: LucideIcon }[] = [
  { label: 'Graph', icon: GitBranch },
  { label: 'Live Logs', icon: TerminalSquare },
  { label: 'Daemon', icon: CircleDot },
];

export function Sidebar({ projects, selectedProject, activeView, loadState, busy, showArchived, onRefresh, onCreateProject, onSelectProject, onArchiveProject, onRestoreProject, onShowArchivedChange, onViewChange }: SidebarProps) {
  return (
    <aside className="sidebar" aria-label="Projects">
      <div className="brand-row">
        <SquareStack size={22} />
        <div>
          <h1>HWE Console</h1>
          <span>Project workflow</span>
        </div>
      </div>
      <button className="primary-button" onClick={onRefresh} disabled={loadState === 'loading'}>
        <RefreshCw size={16} />
        Refresh
      </button>
      <label className="toggle-row">
        <input type="checkbox" checked={showArchived} onChange={(event) => onShowArchivedChange(event.target.checked)} />
        Show archived
      </label>
      <ProjectCreateForm disabled={busy || loadState === 'loading'} onCreate={onCreateProject} />
      <ProjectList
        projects={projects}
        selectedProject={selectedProject}
        onSelectProject={onSelectProject}
        onArchiveProject={onArchiveProject}
        onRestoreProject={onRestoreProject}
      />
      <div className="placeholder-list" aria-label="Console surfaces">
        {activeMenuItems.map((item) => (
          <button
            key={item.view}
            className={activeView === item.view ? 'placeholder-button selected' : 'placeholder-button'}
            onClick={() => onViewChange(item.view)}
            title={item.label}
          >
            <item.icon size={15} />
            {item.label}
          </button>
        ))}
      </div>
      <div className="placeholder-list" aria-label="Planned surfaces">
        {plannedMenuItems.map((item) => (
          <PlaceholderMenuItem key={item.label} label={item.label} icon={item.icon} />
        ))}
      </div>
    </aside>
  );
}