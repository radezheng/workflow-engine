import type { ProjectRecord } from '../../api';
import { Archive, RotateCcw } from 'lucide-react';

type ProjectListProps = {
  projects: ProjectRecord[];
  selectedProject: ProjectRecord | null;
  onSelectProject: (project: ProjectRecord) => void;
  onArchiveProject: (project: ProjectRecord) => void;
  onRestoreProject: (project: ProjectRecord) => void;
};

export function ProjectList({ projects, selectedProject, onSelectProject, onArchiveProject, onRestoreProject }: ProjectListProps) {
  return (
    <div className="project-list">
      {projects.map((project) => (
        <div
          key={`${project.project_ref}:${project.id}`}
          className={project.id === selectedProject?.id ? 'project-row selected' : 'project-row'}
        >
          <button className="project-button" onClick={() => onSelectProject(project)}>
            <span>{project.name}</span>
            <small>{project.project_ref}{project.status === 'archived' ? ' / archived' : ''}</small>
          </button>
          {project.status === 'archived' ? (
            <button className="icon-button" onClick={() => onRestoreProject(project)} title="Restore project" aria-label={`Restore ${project.name}`}>
              <RotateCcw size={15} />
            </button>
          ) : (
            <button className="icon-button" onClick={() => onArchiveProject(project)} title="Archive project" aria-label={`Archive ${project.name}`}>
              <Archive size={15} />
            </button>
          )}
        </div>
      ))}
    </div>
  );
}