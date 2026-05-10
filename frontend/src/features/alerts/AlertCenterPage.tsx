import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import SeverityBadge from "@/components/common/SeverityBadge";
import Pagination from "@/components/common/Pagination";
import { formatDateTime, shortId } from "@/lib/formatters";
import { useAlertsList } from "./useAlertsList";
import type { AlertListQuery, AlertStatus, AlertChannel } from "./types";

const PAGE_SIZE = 25;

export default function AlertCenterPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, Number(searchParams.get("page")) || 1);
  const channelFilter = searchParams.get("channel") ?? "";
  const statusFilter = searchParams.get("status") ?? "";

  const query = useMemo<AlertListQuery>(() => ({
    page,
    pageSize: PAGE_SIZE,
    channel: (channelFilter || undefined) as AlertChannel | undefined,
    status: (statusFilter || undefined) as AlertStatus | undefined,
  }), [page, channelFilter, statusFilter]);

  const { data, loading, error, reload } = useAlertsList(query);
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = data?.pages ?? 0;

  const handlePageChange = (nextPage: number) => {
    const next = new URLSearchParams(searchParams);
    next.set("page", String(nextPage));
    setSearchParams(next);
  };

  return (
    <div className="page fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">Alert center</h1>
          <div className="page-sub">
            Delivery records · <span className="mono">{total}</span> total
          </div>
        </div>
        <div className="page-actions">
          <button className="btn" type="button" onClick={reload} disabled={loading}>
            {loading ? "Refreshing\u2026" : "Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <div style={{ padding: "10px 14px", background: "var(--sev-high-bg)", border: "1px solid var(--sev-high)", borderRadius: "var(--r-md)", marginBottom: 14, fontSize: 12.5, color: "var(--sev-high)" }}>
          {error}
        </div>
      )}

      <div className="filter-bar">
        <select className="select" value={channelFilter} onChange={(e) => {
          const next = new URLSearchParams(searchParams);
          if (e.target.value) next.set("channel", e.target.value);
          else next.delete("channel");
          next.delete("page");
          setSearchParams(next);
        }}>
          <option value="">all channels</option>
          <option value="email">email</option>
          <option value="in_app">in-app</option>
        </select>
        <select className="select" value={statusFilter} onChange={(e) => {
          const next = new URLSearchParams(searchParams);
          if (e.target.value) next.set("status", e.target.value);
          else next.delete("status");
          next.delete("page");
          setSearchParams(next);
        }}>
          <option value="">all statuses</option>
          <option value="sent">sent</option>
          <option value="failed">failed</option>
          <option value="suppressed">suppressed</option>
          <option value="pending">pending</option>
        </select>
        <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 11, color: "var(--text-mute)" }}>
          {items.length} shown
        </span>
      </div>

      <div className="table-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th style={{ width: 80 }}>SEV</th>
              <th>CHANNEL</th>
              <th>STATUS</th>
              <th>SERVICE</th>
              <th>ACCOUNT</th>
              <th>ANOMALY</th>
              <th>CREATED</th>
              <th>SENT</th>
              <th>ERROR</th>
            </tr>
          </thead>
          <tbody>
            {loading && items.length === 0 ? (
              <tr><td colSpan={9} style={{ textAlign: "center", padding: 40, color: "var(--text-mute)" }}>Loading alerts...</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={9}><div className="empty"><div className="big">NO ALERTS</div></div></td></tr>
            ) : items.map((al) => (
              <tr key={al.alert_id}>
                <td><SeverityBadge severity={al.severity} /></td>
                <td className="mono" style={{ textTransform: "uppercase" }}>{al.channel.replace("_", "-")}</td>
                <td><AlertStatusBadge s={al.status} /></td>
                <td>{al.service}</td>
                <td className="mono" style={{ color: "var(--text-2)" }}>{al.account_id}</td>
                <td>
                  <Link to={`/anomalies/${al.anomaly_id}`} className="mono" style={{ color: "var(--text-mute)" }}>
                    {shortId(al.anomaly_id)}
                  </Link>
                </td>
                <td className="mono" style={{ color: "var(--text-mute)" }}>{formatDateTime(al.created_at)}</td>
                <td className="mono" style={{ color: "var(--text-mute)" }}>{formatDateTime(al.sent_at)}</td>
                <td className="mono" style={{ color: al.error_detail ? "var(--sev-high)" : "var(--text-dim)", fontSize: 11 }}>
                  {al.error_detail || "\u2014"}
                </td>
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

function AlertStatusBadge({ s }: { s: string }) {
  const colorMap: Record<string, string> = {
    sent: "var(--accent)",
    failed: "var(--sev-high)",
    suppressed: "var(--text-mute)",
    pending: "var(--sev-med)",
  };
  return (
    <span style={{ fontFamily: "var(--mono)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.04em", color: colorMap[s] ?? "var(--text-mute)" }}>
      ● {s}
    </span>
  );
}
