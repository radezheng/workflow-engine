import { useEffect, useState } from 'react';
import { Bot, FolderCog, Settings } from 'lucide-react';
import type { ConfigStatus } from '../../api';
import { getConfig } from '../../api';
import { PanelTitle } from '../common/PanelTitle';

type SettingsPanelProps = {
  refreshToken: number;
};

export function SettingsPanel({ refreshToken }: SettingsPanelProps) {
  const [config, setConfig] = useState<ConfigStatus | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setError('');
    void getConfig()
      .then((payload) => { if (active) setConfig(payload); })
      .catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : String(caught)); });
    return () => { active = false; };
  }, [refreshToken]);

  if (error) {
    return <div className="inline-error" role="status">{error}</div>;
  }

  if (!config) {
    return <p className="empty-state">Loading settings</p>;
  }

  return (
    <div className="surface-stack">
      <section className="panel" aria-label="HWE config">
        <PanelTitle icon={<Settings size={17} />} title="Settings" />
        <div className="settings-grid">
          <ConfigRow label="Config" value={config.path ?? 'not found'} />
          <ConfigRow label="Workspace" value={config.default_workspace_root ?? 'not configured'} />
          <ConfigRow label="Prompt Templates" value={config.prompt_template_root ?? 'not configured'} />
          <ConfigRow label="Project DB" value={projectDatabaseLabel(config.project_database)} />
        </div>
      </section>

      <div className="settings-columns">
        <section className="panel" aria-label="Profiles">
          <PanelTitle icon={<FolderCog size={17} />} title="Profiles" />
          {config.profiles.length ? <PillList items={config.profiles} /> : <p className="empty-state">No profiles configured</p>}
        </section>
        <section className="panel" aria-label="AI providers">
          <PanelTitle icon={<Bot size={17} />} title="AI Providers" />
          {config.ai_providers.length ? <PillList items={config.ai_providers} /> : <p className="empty-state">No AI providers configured</p>}
        </section>
      </div>
    </div>
  );
}

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="config-row">
      <span>{label}</span>
      <code>{value}</code>
    </div>
  );
}

function projectDatabaseLabel(database: ConfigStatus['project_database']) {
  if (database.backend !== 'postgres') return database.backend;
  return `${database.backend}://${database.user ?? 'user'}@${database.host ?? 'host'}:${database.port ?? 5432}/${database.database ?? 'database'}?schema=${database.schema ?? 'hwe'}&maxconn=${database.maxconn ?? 5}`;
}

function PillList({ items }: { items: string[] }) {
  return (
    <div className="pill-list">
      {items.map((item) => <span key={item}>{item}</span>)}
    </div>
  );
}