import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Icon from "@/components/common/Icon";
import SeverityBadge from "@/components/common/SeverityBadge";
import Sparkline from "@/features/dashboard/Sparkline";
import { useAlertsList } from "./useAlertsList";
import type { AlertListQuery, AlertStatus, AlertChannel } from "./types";

const PAGE_SIZE = 25;

// ISO-style datetime matching the screenshot: "2026-05-09 14:04:36Z"
function fmtAlertTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}Z`
  );
}

export default function AlertCenterPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState("");

  const page          = Math.max(1, Number(searchParams.get("page")) || 1);
  const channelFilter = searchParams.get("channel") ?? "";
  const statusFilter  = searchParams.get("status") ?? "";

  const query = useMemo<AlertListQuery>(() => ({
    page,
    pageSize: PAGE_SIZE,
    channel: (channelFilter || undefined) as AlertChannel | undefined,
    status:  (statusFilter  || undefined) as AlertStatus  | undefined,
  }), [page, channelFilter, statusFilter]);

  const { data, loading, error, reload } = useAlertsList(query);

  // Tiny KPI count queries (page_size=1 → only .total matters)
  const sentKpi   = useAlertsList(useMemo(() => ({ status: "sent"       as AlertStatus, pageSize: 1, page: 1 }), []));
  const failedKpi = useAlertsList(useMemo(() => ({ status: "failed"     as AlertStatus, pageSize: 1, page: 1 }), []));
  const suppKpi   = useAlertsList(useMemo(() => ({ status: "suppressed" as AlertStatus, pageSize: 1, page: 1 }), []));

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = data?.pages ?? 1;

  const sentCount   = sentKpi.data?.total   ?? 0;
  const failedCount = failedKpi.data?.total ?? 0;
  const suppCount   = suppKpi.data?.total   ?? 0;
  const deliveredAndFailed = sentCount + failedCount;
  const successRate = deliveredAndFailed > 0 ? ((sentCount / deliveredAndFailed) * 100).toFixed(1) : "—";
  const failRate    = deliveredAndFailed > 0 ? ((failedCount / deliveredAndFailed) * 100).toFixed(1) : "—";

  // P95 dispatch from current page items
  const dispatchP95 = useMemo(() => {
    const vals = items
      .filter((al) => al.sent_at && al.created_at)
      .map((al) => (new Date(al.sent_at!).getTime() - new Date(al.created_at).getTime()) / 1000)
      .filter((v) => v > 0)
      .sort((a, b) => a - b);
    if (!vals.length) return null;
    return vals[Math.max(0, Math.ceil(vals.length * 0.95) - 1)];
  }, [items]);

  // Client-side search on loaded page
  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    if (!s) return items;
    return items.filter((al) =>
      `${al.account_id} ${al.service} ${al.region} ${al.dedup_key}`.toLowerCase().includes(s)
    );
  }, [items, search]);

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value); else next.delete(key);
    next.delete("page");
    setSearchParams(next);
  };

  return (
    <div className="page fade-in">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Alert center</h1>
          <div className="page-sub">
            Delivery records · dedup window <span className="mono">15m</span> · cooldown <span className="mono">5m</span>
          </div>
        </div>
      </div>

      {/* KPI tiles */}
      <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)", marginBottom: 14 }}>
        <KpiTile
          label="Delivered 24h"
          value={sentCount}
          sub={`— 0% · ${successRate}% success`}
          spark={[40, 42, 38, 41, 43, 45, 42, 40, 44, 42, 46, 48]}
          sparkColor="var(--accent)"
        />
        <KpiTile
          label="Failed"
          value={failedCount}
          sub={`▲ +2 · ${failRate}% rate`}
          spark={[1, 2, 1, 3, 2, 1, 2, 3, 2, 3, 1, 2]}
          sparkColor="var(--sev-high)"
        />
        <KpiTile
          label="Suppressed"
          value={suppCount}
          sub="— · dedup + cooldown"
          spark={[5, 6, 4, 5, 6, 5, 7, 6, 5, 6, 5, 4]}
          sparkColor="var(--sev-med)"
        />
        <KpiTile
          label="P95 dispatch"
          value={dispatchP95 != null ? dispatchP95.toFixed(1) : "—"}
          unit="s"
          sub="▼ -0.4s · email · in-app combined"
          spark={[3.6, 3.4, 3.5, 3.3, 3.2, 3.4, 3.3, 3.2, 3.1, 3.2, 3.3, 3.2]}
          sparkColor="var(--sev-med)"
        />
      </div>

      {error && (
        <div style={{ padding: "10px 14px", background: "var(--sev-high-bg)", border: "1px solid var(--sev-high)", borderRadius: "var(--r-md)", marginBottom: 14, fontSize: 12.5, color: "var(--sev-high)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>{error}</span>
          <button className="btn sm" type="button" onClick={reload}>Retry</button>
        </div>
      )}

      {/* Filter bar */}
      <div className="filter-bar" style={{ marginTop: 14 }}>
        <input
          className="input search"
          placeholder="search alerts…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="select" value={channelFilter} onChange={(e) => setFilter("channel", e.target.value)}>
          <option value="">all channels</option>
          <option value="email">email</option>
          <option value="in_app">in-app</option>
        </select>
        <select className="select" value={statusFilter} onChange={(e) => setFilter("status", e.target.value)}>
          <option value="">all statuses</option>
          <option value="sent">sent</option>
          <option value="failed">failed</option>
          <option value="suppressed">suppressed</option>
          <option value="pending">pending</option>
        </select>
        <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 11, color: "var(--text-mute)" }}>
          {filtered.length} of {total}
        </span>
      </div>

      {/* Table */}
      <div className="table-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th style={{ width: 84 }}>SEV</th>
              <th>CHANNEL</th>
              <th>STATUS</th>
              <th>SERVICE</th>
              <th>ACCOUNT</th>
              <th>DEDUP KEY</th>
              <th>CREATED</th>
              <th className="num">DISPATCH</th>
              <th>ERROR</th>
              <th style={{ width: 24 }} />
            </tr>
          </thead>
          <tbody>
            {loading && items.length === 0 && (
              <tr>
                <td colSpan={10} style={{ textAlign: "center", padding: 40, color: "var(--text-mute)", fontFamily: "var(--mono)", fontSize: 12 }}>
                  loading…
                </td>
              </tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr>
                <td colSpan={10}>
                  <div className="empty"><div className="big">NO ALERTS</div></div>
                </td>
              </tr>
            )}
            {filtered.map((al) => {
              const dispatchMs = al.sent_at
                ? new Date(al.sent_at).getTime() - new Date(al.created_at).getTime()
                : null;
              const dispatchS = dispatchMs != null && dispatchMs > 0
                ? `${(dispatchMs / 1000).toFixed(1)}s`
                : "—";
              return (
                <tr key={al.alert_id}>
                  <td><SeverityBadge severity={al.severity} /></td>
                  <td className="mono" style={{ fontSize: 11.5, textTransform: "uppercase" }}>
                    {al.channel.toUpperCase()}
                  </td>
                  <td><AlertStatusDot s={al.status} /></td>
                  <td>{al.service}</td>
                  <td className="mono" style={{ color: "var(--text-2)" }}>{al.account_id}</td>
                  <td
                    className="mono"
                    style={{ color: "var(--text-mute)", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    title={al.dedup_key}
                  >
                    {al.dedup_key}
                  </td>
                  <td className="mono" style={{ color: "var(--text-mute)" }}>{fmtAlertTime(al.created_at)}</td>
                  <td className="num">{dispatchS}</td>
                  <td
                    className="mono"
                    style={{ color: al.error_detail ? "var(--sev-high)" : "var(--text-dim)", fontSize: 11 }}
                  >
                    {al.error_detail ?? "—"}
                  </td>
                  <td>
                    <Link to={`/anomalies/${al.anomaly_id}`} style={{ color: "var(--text-dim)" }}>
                      <Icon name="chevron-right" size={14} />
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {pages > 1 && (
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 10, alignItems: "center" }}>
          <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--text-mute)" }}>
            {((page - 1) * PAGE_SIZE + 1)}–{Math.min(page * PAGE_SIZE, total)} of {total}
          </div>
          <div className="row gap-8">
            <button className="btn sm" type="button" disabled={page === 1} onClick={() => {
              const next = new URLSearchParams(searchParams);
              next.set("page", String(page - 1));
              setSearchParams(next);
            }}>
              <Icon name="chevron-left" size={12} /> Prev
            </button>
            <span style={{ fontFamily: "var(--mono)", fontSize: 11.5, color: "var(--text-mute)" }}>{page}/{pages}</span>
            <button className="btn sm" type="button" disabled={page >= pages} onClick={() => {
              const next = new URLSearchParams(searchParams);
              next.set("page", String(page + 1));
              setSearchParams(next);
            }}>
              Next <Icon name="chevron-right" size={12} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---- Sub-components ----

function AlertStatusDot({ s }: { s: string }) {
  const colorMap: Record<string, string> = {
    sent:       "var(--accent)",
    failed:     "var(--sev-high)",
    suppressed: "var(--text-mute)",
    pending:    "var(--sev-med)",
  };
  return (
    <span style={{
      fontFamily: "var(--mono)", fontSize: 11,
      textTransform: "uppercase", letterSpacing: "0.04em",
      color: colorMap[s] ?? "var(--text-mute)",
    }}>
      ● {s}
    </span>
  );
}

function KpiTile({
  label, value, unit, sub, spark, sparkColor,
}: {
  label: string;
  value: string | number;
  unit?: string;
  sub: string;
  spark: number[];
  sparkColor: string;
}) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">
        {value}{unit && <span className="unit">{unit}</span>}
      </div>
      <div className="kpi-meta">
        <span style={{ color: "var(--text-dim)" }}>{sub}</span>
      </div>
      <div className="kpi-spark">
        <Sparkline data={spark} width={86} height={28} fill color={sparkColor} />
      </div>
    </div>
  );
}
