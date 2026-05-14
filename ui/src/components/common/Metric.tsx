export function Metric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className={`metric metric-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}