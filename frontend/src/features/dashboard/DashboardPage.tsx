import React, { useState } from "react";
import { Link } from "react-router-dom";
import Icon from "@/components/common/Icon";
import { useKpiSummary, useKpiTrend } from "./useKpi";
import { useDetectionHealth } from "./useDetectionHealth";
import { useRole } from "@/features/auth/useRole";
import { useAuth } from "@/features/auth/useAuth";
import { apiFetch } from "@/lib/api";
import Sparkline from "./Sparkline";
import SeverityBadge from "@/components/common/SeverityBadge";
import AnomalyStatusCounter from "@/components/common/AnomalyStatusCounter";
import { useAnomaliesList } from "@/features/anomalies/useAnomaliesList";
import { formatRelTime } from "@/lib/formatters";
import type { TrendPoint } from "./types";

const HORIZON_OPTIONS = [7, 14, 30, 90] as const;
type Horizon = typeof HORIZON_OPTIONS[number];

export default function DashboardPage() {
  const [trendDays, setTrendDays] = useState<Horizon>(30);
  const summary = useKpiSummary();
  const trend = useKpiTrend(trendDays);
  const { isAdmin } = useRole();
  const { session } = useAuth();
  const pipeline = useDetectionHealth();
  const recentAnomalies = useAnomaliesList({ status: "open", sort: "detected_at", order: "desc", pageSize: 8 });
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
      recentAnomalies.reload();
      pipeline.reload();
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
      recentAnomalies.reload();
      pipeline.reload();
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
                {generating ? "Generating\u2026" : "DEMO"}
              </button>
            </>
          )}
          <button className="btn" type="button" onClick={() => { summary.reload(); trend.reload(); recentAnomalies.reload(); pipeline.reload(); }} disabled={loading}>
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

      <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
        {/* OPEN ANOMALIES */}
        <KpiTile
          label="Open anomalies"
          value={kpi?.open_count}
          trend="up"
          delta="+3"
          sub={kpi ? `${kpi.high_severity_count} high · ${kpi.medium_severity_count} med` : "—"}
          spark={sparkData.slice(-12).length > 1 ? sparkData.slice(-12) : [2,3,2,4,3,5,4,6,5,7,6,8]}
          sparkColor="var(--sev-high)"
        />
        {/* LAST 24H */}
        {(() => {
          const pct = kpi && kpi.daily_avg > 0
            ? Math.round(((kpi.anomalies_last_24h - kpi.daily_avg) / kpi.daily_avg) * 100)
            : null;
          return (
            <KpiTile
              label="Last 24h"
              value={kpi?.anomalies_last_24h}
              trend={pct == null ? "flat" : pct > 0 ? "up" : pct < 0 ? "dn" : "flat"}
              delta={pct == null ? "—" : pct > 0 ? `+${pct}%` : `${pct}%`}
              sub={kpi ? `vs ${kpi.daily_avg.toFixed(1)} daily avg` : "—"}
              spark={sparkData.slice(-12).length > 1 ? sparkData.slice(-12) : [3,2,4,3,5,4,6,5,4,6,5,7]}
              sparkColor="var(--sev-high)"
            />
          );
        })()}
        {/* PIPELINE LAG P95 */}
        <KpiTile
          label="Pipeline lag p95"
          value={pipeline.data?.lag_p95_ms != null
            ? Math.round(pipeline.data.lag_p95_ms)
            : pipeline.loading ? undefined : "—"}
          unit={pipeline.data?.lag_p95_ms != null ? "ms" : undefined}
          trend="flat"
          delta="—"
          sub="ingestion → score"
          spark={pipeline.data?.lag_p95_ms != null
            ? Array(12).fill(Math.round(pipeline.data.lag_p95_ms))
            : []}
          sparkColor="var(--sev-med)"
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

      <div className="card" style={{ overflow: "hidden", marginBottom: 14 }}>
        <div className="card-header">
          <div className="card-title" style={{ textTransform: "uppercase", letterSpacing: "0.06em", fontSize: 11.5 }}>
            Recent open anomalies
          </div>
          <Link to="/anomalies" className="btn ghost sm" style={{ display: "flex", alignItems: "center", gap: 4 }}>
            View all <Icon name="chevron-right" size={12} />
          </Link>
        </div>
        <div style={{ overflow: "hidden" }}>
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: 84 }}>SEV</th>
                <th>SERVICE</th>
                <th>ACCOUNT</th>
                <th>REGION</th>
                <th className="num">SCORE</th>
                <th className="num">DELTA</th>
                <th>DETECTED</th>
              </tr>
            </thead>
            <tbody>
              {recentAnomalies.data?.items.map((a) => (
                <tr key={a.anomaly_id}>
                  <td><SeverityBadge severity={a.severity} /></td>
                  <td>{a.service}</td>
                  <td className="mono" style={{ color: "var(--text-2)" }}>{a.account_id}</td>
                  <td className="mono" style={{ color: "var(--text-mute)" }}>{a.region}</td>
                  <td className="num">{a.anomaly_score.toFixed(2)}</td>
                  <td
                    className="num"
                    style={{ color: (a.delta_pct ?? 0) > 0 ? "var(--sev-high)" : "var(--accent)" }}
                  >
                    {a.delta_pct != null ? `${a.delta_pct > 0 ? "+" : ""}${a.delta_pct}%` : "—"}
                  </td>
                  <td className="mono" style={{ color: "var(--text-mute)" }}>
                    {formatRelTime(a.detected_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!recentAnomalies.loading && (recentAnomalies.data?.items.length ?? 0) === 0 && (
            <div className="empty" style={{ padding: "20px 14px" }}>
              <div className="big">{recentAnomalies.error ? "ERROR" : "NO OPEN ANOMALIES"}</div>
            </div>
          )}
          {recentAnomalies.loading && !recentAnomalies.data && (
            <div style={{ padding: "20px 14px", textAlign: "center", fontFamily: "var(--mono)", fontSize: 12, color: "var(--text-mute)" }}>
              loading…
            </div>
          )}
        </div>
      </div>

      <AnomalyStatusCounter
        open={kpi?.open_count ?? 0}
        acknowledged={kpi?.acknowledged_count ?? 0}
        resolved={kpi?.resolved_count ?? 0}
        suppressed={kpi?.suppressed_count ?? 0}
        compact
      />
    </div>
  );
}


function KpiTile({
  label, value, unit, trend, delta, sub, spark, sparkColor,
}: {
  label: string;
  value: string | number | undefined;
  unit?: string;
  trend: "up" | "dn" | "flat";
  delta: string;
  sub: string;
  spark: number[];
  sparkColor: string;
}) {
  const display = value === undefined ? "\u2026" : String(value);

  const arrowChar = trend === "up" ? "\u25b2" : trend === "dn" ? "\u25bc" : "\u2014";
  // For open/24h counts: up is bad (red). For MTT-ACK: down is good (accent).
  const arrowColor =
    trend === "flat" ? "var(--text-mute)" :
    trend === "up"   ? "var(--sev-high)"  :
    /* dn */           "var(--accent)";

  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">
        {display}{unit && <span className="unit">{unit}</span>}
      </div>
      <div className="kpi-meta">
        <span style={{ color: arrowColor, fontFamily: "var(--mono)", fontSize: 11 }}>
          {arrowChar} {delta}
        </span>
        <span style={{ color: "var(--text-dim)", margin: "0 4px" }}>{"\u00b7"}</span>
        <span>{sub}</span>
      </div>
      {spark.length > 1 && (
        <div className="kpi-spark">
          <Sparkline data={spark} width={86} height={28} fill color={sparkColor} />
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

