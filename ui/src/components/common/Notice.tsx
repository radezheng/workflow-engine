import { AlertCircle } from 'lucide-react';

export function Notice({ message }: { message: string }) {
  if (!message) {
    return null;
  }
  return (
    <div className="notice" role="status">
      <AlertCircle size={16} />
      <span>{message}</span>
    </div>
  );
}