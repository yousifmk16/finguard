import { Link } from "react-router-dom";
import RoleGate from "@/components/auth/RoleGate";
import Sparkline from "./Sparkline";
import { useKpiSummary, useKpiTrend } from "./useKpi";
import type { KpiSummary } from "./types";

const TREND_DAYS = 14;

export default function DashboardPage() {
  const summary = useKpiSummary();
  const trend = useKpiTrend(TREND_DAYS);

  const loading = summary.loading || trend.loading;
  const reloadAll = () => { summary.reload(); trend.reload(); };

  return (
    <section className="fade-in">
      {/* Header */}
      <header className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="sub">Real-time anomaly health across cloud accounts.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <RoleGate roles={["admin"]}>
            <Link to="/policies" className="btn btn--sm">Policies</Link>
          </RoleGate>
          <button type="button" className="btn btn--primary btn--sm btn--pill" onClick={reloadAll} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </header>

      {/* Error */}
      {summary.error ? (
        <div className="state-banner state-banner--error" role="alert">
          <span>{summary.error}</span>
          <button type="button" onClick={summary.reload}>Try again</button>
        </div>
      ) : null}

      {/* Admin callout */}
      <RoleGate roles={["admin"]}>
        <aside className="admin-callout" role="note">
          <span className="admin-callout__badge">Admin</span>
          <span>
            Tune detection thresholds in{" "}
            <Link to="/policies">Policies</Link> or review accounts in{" "}
            <Link to="/users">Users</Link>.
          </span>
        </aside>
      </RoleGate>

      {/* KPI cards */}
      <div className="kpi-cards">
        <KpiCard
          label="Total anomalies"
          value={summary.data?.total_anomalies}
          loading={!summary.data && summary.loading}
          to="/anomalies"
        />
        <KpiCard
          label="Open"
          value={summary.data?.open_count}
          loading={!summary.data && summary.loading}
          tone="danger"
          to="/anomalies?status=open"
        />
        <KpiCard
          label="Last 24 hours"
          value={summary.data?.anomalies_last_24h}
          loading={!summary.data && summary.loading}
          tone="accent"
        />
        <KpiCard
          label="High severity"
          value={summary.data?.high_severity_count}
          loading={!summary.data && summary.loading}
          tone="danger"
          to="/anomalies?severity=high"
        />
      </div>

      {/* Trend + status */}
      <div className="dashboard-grid" style={{ marginBottom: 16 }}>
        <article className="card">
          <div className="card__header">
            <h2>Anomalies — last {TREND_DAYS} days</h2>
            {trend.data && (
              <span className="card__sub">
                {trend.data.points.reduce((s, p) => s + p.count, 0)} total
              </span>
            )}
          </div>
          <div style={{ padding: "14px var(--card-pad) var(--card-pad)" }}>
            {trend.error ? (
              <p style={{ color: "var(--text-muted)", fontSize: 13, margin: 0 }}>{trend.error}</p>
            ) : (
              <Sparkline
                points={trend.data?.points ?? []}
                ariaLabel={`Daily anomaly counts — last ${TREND_DAYS} days`}
                showPeak
                height={90}
              />
            )}
          </div>
        </article>

        <article className="card">
          <div className="card__header"><h2>Status breakdown</h2></div>
          <div className="card__body">
            <BreakdownBars data={statusBreakdown(summary.data)} emptyLabel="No anomalies yet." />
          </div>
        </article>
      </div>

      {/* Severity + top services + top accounts */}
      <div className="dashboard-grid--3">
        <article className="card">
          <div className="card__header"><h2>Severity breakdown</h2></div>
          <div className="card__body">
            <BreakdownBars data={severityBreakdown(summary.data)} emptyLabel="No anomalies yet." />
          </div>
        </article>

        <article className="card">
          <div className="card__header"><h2>Top services</h2></div>
          <div className="card__body">
            <RankedList
              items={summary.data?.top_services.map((s) => ({
                key: s.service, label: s.service, value: s.count,
              })) ?? []}
              emptyLabel="No anomalies yet."
            />
          </div>
        </article>

        <article className="card">
          <div className="card__header"><h2>Top accounts</h2></div>
          <div className="card__body">
            <RankedList
              items={summary.data?.top_accounts.map((a) => ({
                key: a.account_id, label: a.account_id, value: a.count,
              })) ?? []}
              emptyLabel="No anomalies yet."
            />
          </div>
        </article>
      </div>
    </section>
  );
}

/* ---- KPI card -------------------------------------------------- */
interface KpiCardProps {
  label: string;
  value: number | undefined;
  loading: boolean;
  tone?: "default" | "danger" | "accent";
  to?: string;
}

function KpiCard({ label, value, loading, tone = "default", to }: KpiCardProps) {
  const display = loading ? "…" : value === undefined ? "—" : value.toLocaleString();
  const cls = `kpi-card${tone !== "default" ? ` kpi-card--${tone}` : ""}`;
  const inner = (
    <>
      <span className="kpi-card__label">{label}</span>
      <span className="kpi-card__value">{display}</span>
    </>
  );
  if (to) {
    return <Link to={to} className={cls} style={{ display: "flex", flexDirection: "column", gap: 8 }}>{inner}</Link>;
  }
  return <div className={cls}>{inner}</div>;
}

/* ---- Breakdown bars -------------------------------------------- */
interface BreakdownItem { label: string; value: number; modifier: string; color: string; }

function BreakdownBars({ data, emptyLabel }: { data: BreakdownItem[] | null; emptyLabel: string }) {
  if (!data) return <p style={{ color: "var(--text-muted)", fontSize: 13, margin: 0 }}>Loading…</p>;
  const total = data.reduce((s, d) => s + d.value, 0);
  if (total === 0) return <p style={{ color: "var(--text-muted)", fontSize: 13, margin: 0 }}>{emptyLabel}</p>;
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <ul className="breakdown">
      {data.map((d) => (
        <li key={d.label} className={`breakdown__row breakdown__row--${d.modifier}`}>
          <span className="breakdown__label">
            <span className="breakdown__dot" style={{ background: d.color }} />
            {d.label}
          </span>
          <div className="breakdown__track" aria-hidden="true">
            <div className="breakdown__fill" style={{ width: `${(d.value / max) * 100}%` }} />
          </div>
          <span className="breakdown__value">{d.value.toLocaleString()}</span>
        </li>
      ))}
    </ul>
  );
}

/* ---- Ranked list ----------------------------------------------- */
interface RankedItem { key: string; label: string; value: number; }

function RankedList({ items, emptyLabel }: { items: RankedItem[]; emptyLabel: string }) {
  if (items.length === 0) {
    return <p style={{ color: "var(--text-muted)", fontSize: 13, margin: 0 }}>{emptyLabel}</p>;
  }
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <ol className="ranked-list">
      {items.map((item) => (
        <li key={item.key}>
          <span className="ranked-list__rank" />
          <span className="ranked-list__label">{item.label}</span>
          <div className="ranked-list__bar" aria-hidden="true">
            <div className="ranked-list__fill" style={{ width: `${(item.value / max) * 100}%` }} />
          </div>
          <span className="ranked-list__value">{item.value.toLocaleString()}</span>
        </li>
      ))}
    </ol>
  );
}

/* ---- Data transforms ------------------------------------------- */
function statusBreakdown(s: KpiSummary | null): BreakdownItem[] | null {
  if (!s) return null;
  return [
    { label: "Open",         value: s.open_count,         modifier: "open",         color: "var(--c-high)" },
    { label: "Acknowledged", value: s.acknowledged_count, modifier: "acknowledged", color: "var(--c-med)" },
    { label: "Resolved",     value: s.resolved_count,     modifier: "resolved",     color: "var(--c-good)" },
    { label: "Suppressed",   value: s.suppressed_count,   modifier: "suppressed",   color: "var(--text-dim)" },
  ];
}

function severityBreakdown(s: KpiSummary | null): BreakdownItem[] | null {
  if (!s) return null;
  return [
    { label: "High",   value: s.high_severity_count,   modifier: "high",   color: "var(--c-high)" },
    { label: "Medium", value: s.medium_severity_count, modifier: "medium", color: "var(--c-med)" },
    { label: "Low",    value: s.low_severity_count,    modifier: "low",    color: "var(--c-low)" },
  ];
}
