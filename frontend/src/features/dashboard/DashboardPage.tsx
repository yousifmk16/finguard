import { Link } from "react-router-dom";
import RoleGate from "@/components/auth/RoleGate";
import Sparkline from "./Sparkline";
import { useKpiSummary, useKpiTrend } from "./useKpi";
import type { KpiSummary } from "./types";

const TREND_DAYS = 14;

export default function DashboardPage() {
  const summary = useKpiSummary();
  const trend = useKpiTrend(TREND_DAYS);

  const reloadAll = () => {
    summary.reload();
    trend.reload();
  };

  const loading = summary.loading || trend.loading;
  const summaryEmpty = summary.data === null;

  return (
    <section className="dashboard-page">
      <header className="dashboard-page__header">
        <div>
          <h1>Dashboard</h1>
          <p className="dashboard-page__subtitle">
            Real-time anomaly health across cloud accounts.
          </p>
        </div>
        <button
          type="button"
          className="anomalies-page__refresh"
          onClick={reloadAll}
          disabled={loading}
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </header>

      {summary.error ? (
        <div className="state-banner state-banner--error" role="alert">
          <span>{summary.error}</span>
          <button type="button" onClick={summary.reload}>
            Try again
          </button>
        </div>
      ) : null}

      <RoleGate roles={["admin"]}>
        <aside className="admin-callout" role="note">
          <span className="admin-callout__badge">Admin</span>
          <span>
            Tune detection thresholds in <Link to="/policies">Policies</Link> or
            review accounts in <Link to="/users">Users</Link>.
          </span>
        </aside>
      </RoleGate>

      <div className="kpi-cards">
        <KpiCard
          label="Total anomalies"
          value={summary.data?.total_anomalies}
          loading={summaryEmpty && summary.loading}
          to="/anomalies"
        />
        <KpiCard
          label="Open"
          value={summary.data?.open_count}
          loading={summaryEmpty && summary.loading}
          tone="danger"
          to="/anomalies?status=open"
        />
        <KpiCard
          label="Last 24 hours"
          value={summary.data?.anomalies_last_24h}
          loading={summaryEmpty && summary.loading}
        />
        <KpiCard
          label="High severity"
          value={summary.data?.high_severity_count}
          loading={summaryEmpty && summary.loading}
          tone="danger"
          to="/anomalies?severity=high"
        />
      </div>

      <div className="dashboard-grid">
        <article className="card dashboard-card">
          <header className="card__header">
            <h2>Anomalies — last {TREND_DAYS} days</h2>
          </header>
          {trend.error ? (
            <p className="dashboard-card__empty">{trend.error}</p>
          ) : (
            <Sparkline
              points={trend.data?.points ?? []}
              ariaLabel={`Daily anomaly counts for the last ${TREND_DAYS} days`}
            />
          )}
          {trend.data && trend.data.points.length > 0 ? (
            <p className="sparkline__caption">
              Total over window:{" "}
              <strong>{trend.data.points.reduce((sum, p) => sum + p.count, 0)}</strong>
            </p>
          ) : null}
        </article>

        <article className="card dashboard-card">
          <header className="card__header">
            <h2>Status breakdown</h2>
          </header>
          <BreakdownBars data={statusBreakdown(summary.data)} emptyLabel="No anomalies yet." />
        </article>

        <article className="card dashboard-card">
          <header className="card__header">
            <h2>Severity breakdown</h2>
          </header>
          <BreakdownBars data={severityBreakdown(summary.data)} emptyLabel="No anomalies yet." />
        </article>

        <article className="card dashboard-card">
          <header className="card__header">
            <h2>Top services</h2>
          </header>
          <RankedList
            items={
              summary.data?.top_services.map((s) => ({
                key: s.service,
                label: s.service,
                value: s.count,
              })) ?? []
            }
            emptyLabel="No anomalies yet."
          />
        </article>

        <article className="card dashboard-card">
          <header className="card__header">
            <h2>Top accounts</h2>
          </header>
          <RankedList
            items={
              summary.data?.top_accounts.map((a) => ({
                key: a.account_id,
                label: a.account_id,
                value: a.count,
              })) ?? []
            }
            emptyLabel="No anomalies yet."
          />
        </article>
      </div>
    </section>
  );
}

interface KpiCardProps {
  label: string;
  value: number | undefined;
  loading: boolean;
  tone?: "default" | "danger";
  to?: string;
}

function KpiCard({ label, value, loading, tone = "default", to }: KpiCardProps) {
  const display = loading
    ? "..."
    : value === undefined
      ? "—"
      : value.toLocaleString();
  const className = `kpi-card kpi-card--${tone}`;
  const inner = (
    <>
      <span className="kpi-card__label">{label}</span>
      <span className="kpi-card__value">{display}</span>
    </>
  );

  if (to) {
    return (
      <Link to={to} className={`${className} kpi-card--link`}>
        {inner}
      </Link>
    );
  }
  return <div className={className}>{inner}</div>;
}

interface BreakdownItem {
  label: string;
  value: number;
  modifier: string;
}

function BreakdownBars({
  data,
  emptyLabel,
}: {
  data: BreakdownItem[] | null;
  emptyLabel: string;
}) {
  if (!data) return <p className="dashboard-card__empty">Loading...</p>;
  const max = Math.max(...data.map((d) => d.value), 1);
  const total = data.reduce((sum, d) => sum + d.value, 0);
  if (total === 0) return <p className="dashboard-card__empty">{emptyLabel}</p>;

  return (
    <ul className="breakdown">
      {data.map((d) => (
        <li key={d.label} className={`breakdown__row breakdown__row--${d.modifier}`}>
          <span className="breakdown__label">{d.label}</span>
          <div className="breakdown__track" aria-hidden="true">
            <div
              className="breakdown__fill"
              style={{ width: `${(d.value / max) * 100}%` }}
            />
          </div>
          <span className="breakdown__value">{d.value.toLocaleString()}</span>
        </li>
      ))}
    </ul>
  );
}

interface RankedItem {
  key: string;
  label: string;
  value: number;
}

function RankedList({
  items,
  emptyLabel,
}: {
  items: RankedItem[];
  emptyLabel: string;
}) {
  if (items.length === 0) {
    return <p className="dashboard-card__empty">{emptyLabel}</p>;
  }
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <ol className="ranked-list">
      {items.map((item) => (
        <li key={item.key}>
          <span className="ranked-list__label">{item.label}</span>
          <div className="ranked-list__track" aria-hidden="true">
            <div
              className="ranked-list__fill"
              style={{ width: `${(item.value / max) * 100}%` }}
            />
          </div>
          <span className="ranked-list__value">{item.value.toLocaleString()}</span>
        </li>
      ))}
    </ol>
  );
}

function statusBreakdown(s: KpiSummary | null): BreakdownItem[] | null {
  if (!s) return null;
  return [
    { label: "Open", value: s.open_count, modifier: "open" },
    { label: "Acknowledged", value: s.acknowledged_count, modifier: "acknowledged" },
    { label: "Resolved", value: s.resolved_count, modifier: "resolved" },
    { label: "Suppressed", value: s.suppressed_count, modifier: "suppressed" },
  ];
}

function severityBreakdown(s: KpiSummary | null): BreakdownItem[] | null {
  if (!s) return null;
  return [
    { label: "High", value: s.high_severity_count, modifier: "high" },
    { label: "Medium", value: s.medium_severity_count, modifier: "medium" },
    { label: "Low", value: s.low_severity_count, modifier: "low" },
  ];
}
