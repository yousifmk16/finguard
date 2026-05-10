import { useState } from "react";
import { Link } from "react-router-dom";
import Icon from "@/components/common/Icon";
import { useKpiSummary, useKpiTrend } from "./useKpi";
import { useRole } from "@/features/auth/useRole";
import { useAuth } from "@/features/auth/useAuth";
import { apiFetch } from "@/lib/api";
import Sparkline from "./Sparkline";
import type { KpiSummary, TrendPoint } from "./types";

const HORIZON_OPTIONS = [7, 14, 30, 90] as const;
type Horizon = typeof HORIZON_OPTIONS[number];

export default function DashboardPage() {
  const [trendDays, setTrendDays] = useState<Horizon>(30);
  const summary = useKpiSummary();
  const trend = useKpiTrend(trendDays);
  const { isAdmin } = useRole();
  const { session } = useAuth();
  const [generating, setGenerating] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [genResult, setGenResult] = useState<string | null>(null);

  const kpi = summary.data;
  const trendData = trend.data?.points ?? [];
  const sparkData = trendData.map((t) => t.count);
  const loading = summary.loading || trend.loading;

  const handleGenerate = async () => {
    if (!session) return;
    setGenerating(true);
    setGenResult(null);
    try {
      const res = await apiFetch<{ accepted: number; anomalies_seeded: number; alerts_seeded: number; seed_used: number }>(
        "/admin/generate",
        { method: "POST", token: session.token, body: {} }
      );
      setGenResult(`✓ ${res.accepted} events · ${res.anomalies_seeded} anomalies · ${res.alerts_seeded} alerts (seed ${res.seed_used})`);
      summary.reload();
      trend.reload();
    } catch (e: unknown) {
      setGenResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setGenerating(false);
    }
  };

  const handleDelete = async () => {
    if (!session) return;
    setDeleting(true);
    setGenResult(null);
    try {
      const res = await apiFetch<{ events_deleted: number; anomalies_deleted: number; alerts_deleted: number }>(
        "/admin/data",
        { method: "DELETE", token: session.token }
      );
      setGenResult(`✓ Cleared — ${res.events_deleted} events, ${res.anomalies_deleted} anomalies, ${res.alerts_deleted} alerts deleted`);
      summary.reload();
      trend.reload();
    } catch (e: unknown) {
      setGenResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="page fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">Operations</h1>
          <div className="page-sub">
            Real-time view of detection pipeline and anomaly volume.
          </div>
        </div>
        <div className="page-actions">
          {isAdmin && (
            <>
              <button className="btn ghost" type="button" onClick={handleDelete} disabled={deleting || generating}
                style={{ color: "var(--sev-high)", borderColor: "var(--sev-high)" }}>
                {deleting ? "Clearing\u2026" : "Clear data"}
              </button>
              <button className="btn ghost" type="button" onClick={handleGenerate} disabled={generating || deleting}>
                <Icon name="sparkles" size={14} />
                {generating ? "Generating\u2026" : "Generate data"}
              </button>
            </>
          )}
          <button className="btn" type="button" onClick={() => { summary.reload(); trend.reload(); }} disabled={loading}>
            {loading ? "Refreshing\u2026" : "Refresh"}
          </button>
        </div>
      </div>

      {genResult && (
        <div style={{ padding: "10px 14px", background: genResult.startsWith("✓") ? "var(--accent-dim)" : "var(--sev-high-bg)", border: `1px solid ${genResult.startsWith("✓") ? "var(--accent)" : "var(--sev-high)"}`, borderRadius: "var(--r-md)", marginBottom: 14, fontSize: 12.5, color: genResult.startsWith("✓") ? "var(--accent)" : "var(--sev-high)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>{genResult}</span>
          <button type="button" onClick={() => setGenResult(null)} style={{ background: "none", border: "none", cursor: "pointer", color: "inherit", fontSize: 14 }}>✕</button>
        </div>
      )}

      {summary.error && (
        <div style={{ padding: "10px 14px", background: "var(--sev-high-bg)", border: "1px solid var(--sev-high)", borderRadius: "var(--r-md)", marginBottom: 14, fontSize: 12.5, color: "var(--sev-high)" }}>
          {summary.error}
          <button className="btn sm" style={{ marginLeft: 12 }} onClick={summary.reload} type="button">Retry</button>
        </div>
      )}

      <div className="kpi-grid">
        <KpiTile
          label="Open anomalies"
          value={kpi?.open_count}
          sub={kpi ? `${kpi.high_severity_count} high · ${kpi.medium_severity_count} med` : ""}
          spark={[]}
        />
        <KpiTile
          label="Last 24h"
          value={kpi?.anomalies_last_24h}
          sub="recent window"
          spark={sparkData.slice(-7)}
        />
        <KpiTile
          label="Total anomalies"
          value={kpi?.total_anomalies}
          sub="all time"
          spark={sparkData}
        />
        <KpiTile
          label="Acknowledged"
          value={kpi?.acknowledged_count}
          sub={kpi ? `${kpi.resolved_count} resolved` : ""}
          spark={[]}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 14, marginBottom: 14 }}>
        <div className="card">
          <div className="card-header">
            <div className="card-title">Anomaly volume</div>
            <div className="row gap-4">
              {HORIZON_OPTIONS.map((d) => (
                <button
                  key={d}
                  type="button"
                  className={`btn ghost sm${trendDays === d ? " active" : ""}`}
                  onClick={() => setTrendDays(d)}
                  style={trendDays === d ? { background: "var(--accent-dim)", color: "var(--accent)", borderColor: "var(--accent)" } : {}}
                >
                  {d}d
                </button>
              ))}
            </div>
          </div>
          <div className="card-body" style={{ paddingBottom: 6 }}>
            {trendData.length > 0 ? (
              <BarChart data={trendData} width={780} height={130} />
            ) : (
              <div className="empty" style={{ padding: 20 }}>
                <div className="big">{loading ? "LOADING\u2026" : "NO DATA"}</div>
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title">Top services</div>
            <span className="badge-soft">{kpi?.total_anomalies ?? 0} total</span>
          </div>
          <div className="card-body">
            {kpi?.top_services.slice(0, 5).map((s) => (
              <div key={s.service} style={{ display: "grid", gridTemplateColumns: "100px 1fr 40px", alignItems: "center", gap: 10, marginBottom: 6 }}>
                <div style={{ fontSize: 12, color: "var(--text-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.service}</div>
                <div style={{ height: 6, background: "var(--surface-3)", borderRadius: 2, position: "relative" }}>
                  <div style={{ position: "absolute", inset: 0, width: `${kpi.top_services[0]?.count ? (s.count / kpi.top_services[0].count) * 100 : 0}%`, background: "var(--accent)", borderRadius: 2, opacity: 0.7 }} />
                </div>
                <div style={{ textAlign: "right", fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--text-mute)" }}>{s.count}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 14, marginBottom: 14 }}>
        <div className="card">
          <div className="card-header">
            <div className="card-title">Status breakdown</div>
            <Link to="/anomalies" className="btn ghost sm">
              View all <Icon name="chevron-right" size={12} />
            </Link>
          </div>
          <div className="card-body">
            {kpi && (
              <div style={{ display: "grid", gap: 10 }}>
                <StatusRow label="Open" count={kpi.open_count} color="var(--status-open)" total={kpi.total_anomalies} />
                <StatusRow label="Acknowledged" count={kpi.acknowledged_count} color="var(--status-ack)" total={kpi.total_anomalies} />
                <StatusRow label="Resolved" count={kpi.resolved_count} color="var(--status-res)" total={kpi.total_anomalies} />
                <StatusRow label="Suppressed" count={kpi.suppressed_count} color="var(--status-sup)" total={kpi.total_anomalies} />
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title">Severity breakdown</div>
          </div>
          <div className="card-body">
            {kpi && (
              <div style={{ display: "grid", gap: 10 }}>
                <StatusRow label="High" count={kpi.high_severity_count} color="var(--sev-high)" total={kpi.total_anomalies} />
                <StatusRow label="Medium" count={kpi.medium_severity_count} color="var(--sev-med)" total={kpi.total_anomalies} />
                <StatusRow label="Low" count={kpi.low_severity_count} color="var(--sev-low)" total={kpi.total_anomalies} />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function KpiTile({ label, value, sub, spark }: {
  label: string;
  value: number | undefined;
  sub: string;
  spark: number[];
}) {
  const display = value === undefined ? "\u2026" : value.toLocaleString();
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{display}</div>
      <div className="kpi-meta">
        <span>{sub}</span>
      </div>
      {spark.length > 1 && (
        <div className="kpi-spark">
          <Sparkline data={spark} width={86} height={28} fill color="var(--accent)" />
        </div>
      )}
    </div>
  );
}


function BarChart({ data, width, height }: { data: TrendPoint[]; width: number; height: number }) {
  if (!data.length) return null;

  const PAD_L = 28;
  const PAD_B = 16;
  const PAD_T = 6;
  const innerW = width - PAD_L;
  const innerH = height - PAD_B - PAD_T;

  const counts = data.map((d) => d.count);
  const max = Math.max(...counts, 1);
  const avg = counts.reduce((a, b) => a + b, 0) / (counts.length || 1);
  const barW = innerW / data.length;
  const yTicks = max <= 2 ? [0, max] : [0, Math.round(max / 2), max];

  const fmtDate = (s: string | Date) => {
    const d = new Date(s);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  };

  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`}>
      {yTicks.map((tick) => {
        const y = PAD_T + innerH - (tick / max) * innerH;
        return (
          <g key={tick}>
            <line x1={PAD_L} x2={PAD_L + innerW} y1={y} y2={y}
              stroke="var(--border)" strokeWidth={tick === 0 ? 1 : 0.5}
              strokeDasharray={tick === 0 ? undefined : "3 4"} />
            <text x={PAD_L - 4} y={y + 3} fontSize="8" fill="var(--text-mute)"
              fontFamily="var(--mono)" textAnchor="end">{tick}</text>
          </g>
        );
      })}

      {data.map((d, i) => {
        const h = (d.count / max) * innerH;
        const x = PAD_L + i * barW + 1;
        const y = PAD_T + innerH - Math.max(d.count > 0 ? 2 : 0, h);
        const isHot = d.count > avg * 2;
        return (
          <rect key={i} x={x} y={y}
            width={Math.max(2, barW - 2)}
            height={d.count > 0 ? Math.max(2, h) : 0}
            fill={isHot ? "var(--sev-high)" : "var(--accent)"}
            opacity={isHot ? 0.88 : 0.62} rx="1" />
        );
      })}

      <text x={PAD_L} y={height - 2} fontSize="8" fill="var(--text-mute)" fontFamily="var(--mono)">
        {fmtDate(data[0].day)}
      </text>
      {data.length > 10 && (
        <text x={PAD_L + innerW / 2} y={height - 2} fontSize="8" fill="var(--text-mute)"
          fontFamily="var(--mono)" textAnchor="middle">
          {fmtDate(data[Math.floor(data.length / 2)].day)}
        </text>
      )}
      <text x={PAD_L + innerW} y={height - 2} fontSize="8" fill="var(--text-mute)"
        fontFamily="var(--mono)" textAnchor="end">Today</text>
    </svg>
  );
}

function StatusRow({ label, count, color, total }: { label: string; count: number; color: string; total: number }) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "100px 1fr 40px", alignItems: "center", gap: 10 }}>
      <div className="row" style={{ gap: 6, fontSize: 12, color: "var(--text-2)" }}>
        <span style={{ width: 8, height: 8, background: color, borderRadius: "50%" }} />
        {label}
      </div>
      <div style={{ height: 6, background: "var(--surface-3)", borderRadius: 2, position: "relative" }}>
        <div style={{ position: "absolute", inset: 0, width: `${pct}%`, background: color, borderRadius: 2, opacity: 0.7 }} />
      </div>
      <div style={{ textAlign: "right", fontFamily: "var(--mono)", fontSize: 11.5 }}>{count}</div>
    </div>
  );
}
