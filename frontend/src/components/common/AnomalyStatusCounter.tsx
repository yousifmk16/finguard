interface AnomalyStatusCounterProps {
  open: number;
  acknowledged: number;
  resolved: number;
  suppressed: number;
  compact?: boolean;
}

const STATUSES = [
  { key: "open",         label: "Open",         dotClass: "status open" },
  { key: "acknowledged", label: "Acknowledged",  dotClass: "status acknowledged" },
  { key: "resolved",     label: "Resolved",      dotClass: "status resolved" },
  { key: "suppressed",   label: "Suppressed",    dotClass: "status suppressed" },
] as const;

export default function AnomalyStatusCounter({ open, acknowledged, resolved, suppressed, compact }: AnomalyStatusCounterProps) {
  const counts: Record<string, number> = { open, acknowledged, resolved, suppressed };

  return (
    <div style={{
      display: "flex",
      gap: 0,
      background: "var(--surface-1)",
      border: "1px solid var(--border)",
      borderRadius: "var(--r-md)",
      overflow: "hidden",
      marginBottom: 14,
    }}>
      {STATUSES.map((s, i) => (
        <div
          key={s.key}
          style={{
            flex: 1,
            padding: compact ? "8px 12px" : "12px 16px",
            borderRight: i < STATUSES.length - 1 ? "1px solid var(--border)" : undefined,
            display: "flex",
            flexDirection: compact ? "row" : "column",
            alignItems: compact ? "center" : undefined,
            justifyContent: compact ? "space-between" : undefined,
            gap: compact ? 8 : 6,
          }}
        >
          <span className={`${s.dotClass}`} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 10.5, color: "var(--text-mute)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            <span className="stat-dot" />
            {s.label}
          </span>
          <div style={{ fontFamily: "var(--mono)", fontSize: compact ? 13 : 22, fontWeight: 600, color: "var(--text-1)", lineHeight: 1 }}>
            {counts[s.key].toLocaleString()}
          </div>
        </div>
      ))}
    </div>
  );
}
