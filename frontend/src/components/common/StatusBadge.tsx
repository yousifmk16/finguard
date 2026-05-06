interface StatusBadgeProps {
  status: string;
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const normalized = status.toLowerCase();
  return <span className={`badge badge--status badge--status-${normalized}`}>{status}</span>;
}
