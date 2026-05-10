import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Icon from "@/components/common/Icon";
import SeverityBadge from "@/components/common/SeverityBadge";
import StatusBadge from "@/components/common/StatusBadge";
import Pagination from "@/components/common/Pagination";
import { formatRelTime, formatScore } from "@/lib/formatters";
import { useAnomaliesList } from "./useAnomaliesList";
import type { AnomalyListQuery, AnomalySeverity, AnomalyStatus } from "./types";

const PAGE_SIZE = 20;

export default function AnomaliesListPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, Number(searchParams.get("page")) || 1);
  const severity = searchParams.get("severity") as AnomalySeverity | null;
  const status = searchParams.get("status") as AnomalyStatus | null;
  const service = searchParams.get("service") ?? "";

  const query = useMemo<AnomalyListQuery>(() => ({
    page,
    pageSize: PAGE_SIZE,
    severity: severity ?? undefined,
    status: status ?? undefined,
    service: service || undefined,
    sort: "detected_at",
    order: "desc",
  }), [page, severity, status, service]);

  const { data, loading, error, reload } = useAnomaliesList(query);
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = data?.pages ?? 0;

  const handlePageChange = (nextPage: number) => {
    const next = new URLSearchParams(searchParams);
    next.set("page", String(nextPage));
    setSearchParams(next);
  };

  const toggleFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (next.get(key) === value) {
      next.delete(key);
    } else {
      next.set(key, value);
    }
    next.delete("page");
    setSearchParams(next);
  };

  return (
    <div className="page fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">Anomalies</h1>
          <div className="page-sub">
            <span className="mono">{total.toLocaleString()}</span> total
          </div>
        </div>
        <div className="page-actions">
          <button className="btn" type="button" onClick={reload} disabled={loading}>
            {loading ? "Refreshing\u2026" : "Refresh"}
          </button>
        </div>
      </div>

      <div className="filter-bar">
        <input
          className="input search"
          placeholder="service, account, region\u2026"
          value={service}
          onChange={(e) => {
            const next = new URLSearchParams(searchParams);
            if (e.target.value) next.set("service", e.target.value);
            else next.delete("service");
            next.delete("page");
            setSearchParams(next);
          }}
        />
        <span style={{ width: 1, height: 18, background: "var(--border)", margin: "0 4px" }} />
        <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase", marginRight: 4 }}>SEV</span>
        {(["high", "medium", "low"] as const).map((s) => (
          <button key={s} type="button" className={`chip ${severity === s ? "active" : ""}`} onClick={() => toggleFilter("severity", s)}>
            <span className="sev-dot" style={{ background: s === "high" ? "var(--sev-high)" : s === "medium" ? "var(--sev-med)" : "var(--sev-low)" }} />
            {s}
          </button>
        ))}
        <span style={{ width: 1, height: 18, background: "var(--border)", margin: "0 6px" }} />
        <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase", marginRight: 4 }}>STATUS</span>
        {(["open", "acknowledged", "resolved", "suppressed"] as const).map((s) => (
          <button key={s} type="button" className={`chip ${status === s ? "active" : ""}`} onClick={() => toggleFilter("status", s)}>{s}</button>
        ))}
      </div>

      {error && (
        <div style={{ padding: "10px 14px", background: "var(--sev-high-bg)", border: "1px solid var(--sev-high)", borderRadius: "var(--r-md)", marginBottom: 14, fontSize: 12.5, color: "var(--sev-high)" }}>
          {error}
        </div>
      )}

      <div className="table-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th style={{ width: 80 }}>SEV</th>
              <th>SERVICE</th>
              <th>ACCOUNT</th>
              <th>REGION</th>
              <th className="num">SCORE</th>
              <th>STATUS</th>
              <th>DETECTED</th>
              <th style={{ width: 24 }} />
            </tr>
          </thead>
          <tbody>
            {loading && items.length === 0 ? (
              <tr><td colSpan={8} style={{ textAlign: "center", padding: 40, color: "var(--text-mute)" }}>Loading anomalies...</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={8}><div className="empty"><div className="big">NO MATCHES</div><div style={{ marginTop: 8, fontSize: 12 }}>Try clearing filters.</div></div></td></tr>
            ) : items.map((a, i) => (
              <tr key={a.anomaly_id} className={i === 0 ? "new" : ""}>
                <td><SeverityBadge severity={a.severity} /></td>
                <td>{a.service}</td>
                <td className="mono" style={{ color: "var(--text-2)" }}>{a.account_id}</td>
                <td className="mono" style={{ color: "var(--text-mute)" }}>{a.region}</td>
                <td className="num">{formatScore(a.anomaly_score)}</td>
                <td><StatusBadge status={a.status} /></td>
                <td className="mono" style={{ color: "var(--text-mute)" }}>{formatRelTime(a.detected_at)}</td>
                <td><Link to={`/anomalies/${a.anomaly_id}`}><Icon name="chevron-right" size={14} /></Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pagination
        page={page}
        pages={pages}
        total={total}
        pageSize={PAGE_SIZE}
        onPageChange={handlePageChange}
        disabled={loading}
      />
    </div>
  );
}
