interface StatusBadgeProps {
  status: string;
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const s = status.toLowerCase();
  return (
    <span className={`status ${s}`}>
      <span className="stat-dot" />
      {s.toUpperCase()}
    </span>
  );
}
