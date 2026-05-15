import type { ProjectRecord } from '../../api';
import { Archive, Ellipsis, RotateCcw } from 'lucide-react';
import { useState } from 'react';

type ProjectListProps = {
  projects: ProjectRecord[];
  selectedProject: ProjectRecord | null;
  onSelectProject: (project: ProjectRecord) => void;
  onArchiveProject: (project: ProjectRecord) => void;
  onRestoreProject: (project: ProjectRecord) => void;
};

export function ProjectList({ projects, selectedProject, onSelectProject, onArchiveProject, onRestoreProject }: ProjectListProps) {
  const [openProjectId, setOpenProjectId] = useState<string | null>(null);
  return (
    <div className="project-list">
      {projects.map((project) => {
        const menuKey = `${project.project_ref}:${project.id}`;
        const menuOpen = openProjectId === menuKey;
        return (
          <div
            key={menuKey}
            className={project.id === selectedProject?.id ? 'project-row selected' : 'project-row'}
          >
            <button className="project-button" onClick={() => onSelectProject(project)}>
              <span>{project.name}</span>
              <small>{project.project_ref}{project.status === 'archived' ? ' / archived' : ''}</small>
            </button>
            <div className="row-menu">
              <button className="icon-button" onClick={() => setOpenProjectId(menuOpen ? null : menuKey)} title="Project actions" aria-label={`Actions for ${project.name}`}>
                <Ellipsis size={16} />
              </button>
              {menuOpen && (
                <div className="row-menu-popover" role="menu">
                  {project.status === 'archived' ? (
                    <button type="button" role="menuitem" onClick={() => { setOpenProjectId(null); onRestoreProject(project); }}>
                      <RotateCcw size={14} />
                      Restore
                    </button>
                  ) : (
                    <button type="button" role="menuitem" onClick={() => { setOpenProjectId(null); onArchiveProject(project); }}>
                      <Archive size={14} />
                      Archive
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}