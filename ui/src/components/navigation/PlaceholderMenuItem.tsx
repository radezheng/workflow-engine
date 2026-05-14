import type { LucideIcon } from 'lucide-react';

export function PlaceholderMenuItem({ label, icon: Icon }: { label: string; icon: LucideIcon }) {
  return (
    <button className="placeholder-button" disabled title={label}>
      <Icon size={15} />
      {label}
    </button>
  );
}