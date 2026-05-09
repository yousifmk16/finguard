export default function PoliciesPage() {
  return (
    <section className="fade-in">
      <header className="page-head">
        <div>
          <h1>Policies</h1>
          <p className="sub">Detection thresholds and alert routing rules.</p>
        </div>
      </header>

      <div className="dashboard-grid" style={{ marginBottom: 16 }}>
        {/* Anomaly scoring */}
        <article className="card">
          <div className="card__header">
            <h2>Anomaly Scoring</h2>
            <span className="card__sub">Weighted ensemble</span>
          </div>
          <div className="card__body">
            <ul className="breakdown">
              <PolicyRow label="Time-series forecast" value={40} color="var(--accent)" />
              <PolicyRow label="Isolation Forest"      value={35} color="var(--c-med)" />
              <PolicyRow label="Deterministic rules"   value={25} color="var(--c-low)" />
            </ul>
          </div>
        </article>

        {/* Severity thresholds */}
        <article className="card">
          <div className="card__header">
            <h2>Severity Thresholds</h2>
            <span className="card__sub">Anomaly score cutoffs</span>
          </div>
          <div className="card__body">
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 12 }}>
              <ThresholdRow label="High"   range="≥ 0.80" color="var(--c-high)"  bg="var(--c-high-bg)"  border="var(--c-high-border)" />
              <ThresholdRow label="Medium" range="0.50 – 0.79" color="var(--c-med)"   bg="var(--c-med-bg)"   border="var(--c-med-border)" />
              <ThresholdRow label="Low"    range="0.20 – 0.49" color="var(--c-low)"   bg="var(--c-low-bg)"   border="var(--c-low-border)" />
              <ThresholdRow label="None"   range="< 0.20"      color="var(--text-dim)" bg="var(--surface-2)" border="var(--border)" />
            </ul>
          </div>
        </article>
      </div>

      {/* Alert routing */}
      <article className="card" style={{ marginBottom: 16 }}>
        <div className="card__header">
          <h2>Alert Routing</h2>
          <span className="card__sub">By severity</span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Severity</th>
                <th>In-App Alert</th>
                <th>Email Alert</th>
                <th>Auto-suppress after</th>
              </tr>
            </thead>
            <tbody>
              <RoutingRow severity="High"   inApp color="var(--c-high)"  email autoSuppress="30 days" />
              <RoutingRow severity="Medium" inApp color="var(--c-med)"   email autoSuppress="14 days" />
              <RoutingRow severity="Low"    inApp color="var(--c-low)"              autoSuppress="7 days" />
              <RoutingRow severity="None"                                color="var(--text-dim)" autoSuppress="—" />
            </tbody>
          </table>
        </div>
      </article>

      <aside className="admin-callout" role="note">
        <span className="admin-callout__badge">Admin</span>
        <span>Policy configuration is managed via environment variables and the detection pipeline. Runtime editing will be available in a future release.</span>
      </aside>
    </section>
  );
}

function PolicyRow({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <li className="breakdown__row">
      <span className="breakdown__label">
        <span className="breakdown__dot" style={{ background: color }} />
        {label}
      </span>
      <div className="breakdown__track" aria-hidden="true">
        <div className="breakdown__fill" style={{ width: `${value}%`, background: color }} />
      </div>
      <span className="breakdown__value">{value}%</span>
    </li>
  );
}

function ThresholdRow({ label, range, color, bg, border }: {
  label: string; range: string; color: string; bg: string; border: string;
}) {
  return (
    <li style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 13 }}>
      <span className="badge" style={{ background: bg, color, borderColor: border }}>{label}</span>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-muted)" }}>{range}</span>
    </li>
  );
}

function RoutingRow({ severity, inApp = false, email = false, color, autoSuppress }: {
  severity: string; inApp?: boolean; email?: boolean; color: string; autoSuppress: string;
}) {
  const check = <span style={{ color: "var(--c-good)" }}>✓</span>;
  const dash  = <span style={{ color: "var(--text-dim)" }}>—</span>;
  return (
    <tr>
      <td><span className="badge" style={{ color }}>{severity}</span></td>
      <td style={{ textAlign: "center" }}>{inApp  ? check : dash}</td>
      <td style={{ textAlign: "center" }}>{email  ? check : dash}</td>
      <td style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 12 }}>{autoSuppress}</td>
    </tr>
  );
}
