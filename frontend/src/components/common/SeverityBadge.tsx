interface SeverityBadgeProps {
  severity: string;
}

export default function SeverityBadge({ severity }: SeverityBadgeProps) {
  const s = severity.toLowerCase();
  return (
    <span className={`sev ${s}`}>
      <span className="sev-dot" />
      {s.toUpperCase()}
    </span>
  );
}
