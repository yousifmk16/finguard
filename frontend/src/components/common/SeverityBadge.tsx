interface SeverityBadgeProps {
  severity: string;
}

export default function SeverityBadge({ severity }: SeverityBadgeProps) {
  const normalized = severity.toLowerCase();
  return <span className={`badge badge--severity badge--severity-${normalized}`}>{severity}</span>;
}
