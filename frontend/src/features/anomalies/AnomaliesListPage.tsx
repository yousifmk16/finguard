import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Pagination from "@/components/common/Pagination";
import SeverityBadge from "@/components/common/SeverityBadge";
import StatusBadge from "@/components/common/StatusBadge";
import { formatDateTime, formatScore, shortId } from "@/lib/formatters";
import { useAnomaliesList } from "./useAnomaliesList";
import type { AnomalyListQuery, AnomalyRecord } from "./types";

const DEFAULT_PAGE_SIZE = 25;
const MAX_PAGE_SIZE = 200;

function clampInt(value: string | null, fallback: number, min = 1, max = Number.MAX_SAFE_INTEGER): number {
  if (value === null) return fallback;
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) return fallback;
  return Math.min(Math.max(parsed, min), max);
}

export default function AnomaliesListPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = clampInt(searchParams.get("page"), 1, 1);
  const pageSize = clampInt(searchParams.get("page_size"), DEFAULT_PAGE_SIZE, 1, MAX_PAGE_SIZE);

  const query = useMemo<AnomalyListQuery>(() => ({ page, pageSize }), [page, pageSize]);
  const { data, loading, error, reload } = useAnomaliesList(query);

  const handlePageChange = (next: number) => {
    const params = new URLSearchParams(searchParams);
    params.set("page", String(next));
    params.set("page_size", String(pageSize));
    setSearchParams(params, { replace: false });
  };

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = data?.pages ?? 0;
  const showSkeleton = loading && data === null;

  return (
    <section className="anomalies-page">
      <header className="anomalies-page__header">
        <div>
          <h1>Anomalies</h1>
          <p className="anomalies-page__subtitle">
            Active and historical anomalies detected across cloud accounts.
          </p>
        </div>
        <button
          type="button"
          className="anomalies-page__refresh"
          onClick={reload}
          disabled={loading}
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </header>

      {error ? (
        <div className="state-banner state-banner--error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={reload}>
            Try again
          </button>
        </div>
      ) : null}

      <div className="data-table__wrapper" aria-busy={loading}>
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">ID</th>
              <th scope="col">Account</th>
              <th scope="col">Service</th>
              <th scope="col">Region</th>
              <th scope="col" className="data-table__col-num">Score</th>
              <th scope="col">Severity</th>
              <th scope="col">Status</th>
              <th scope="col">Detected</th>
              <th scope="col" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {showSkeleton ? (
              <tr>
                <td colSpan={9} className="data-table__placeholder">
                  Loading anomalies...
                </td>
              </tr>
            ) : items.length === 0 && !error ? (
              <tr>
                <td colSpan={9} className="data-table__placeholder">
                  No anomalies match the current view.
                </td>
              </tr>
            ) : (
              items.map((row) => <AnomalyRow key={row.anomaly_id} row={row} />)
            )}
          </tbody>
        </table>
      </div>

      <Pagination
        page={page}
        pages={pages}
        total={total}
        pageSize={pageSize}
        onPageChange={handlePageChange}
        disabled={loading}
      />
    </section>
  );
}

function AnomalyRow({ row }: { row: AnomalyRecord }) {
  return (
    <tr>
      <td>
        <Link to={`/anomalies/${row.anomaly_id}`} title={row.anomaly_id}>
          {shortId(row.anomaly_id)}
        </Link>
      </td>
      <td>{row.account_id}</td>
      <td>{row.service}</td>
      <td>{row.region}</td>
      <td className="data-table__col-num">{formatScore(row.anomaly_score)}</td>
      <td>
        <SeverityBadge severity={row.severity} />
      </td>
      <td>
        <StatusBadge status={row.status} />
      </td>
      <td>{formatDateTime(row.detected_at)}</td>
      <td className="data-table__col-action">
        <Link to={`/anomalies/${row.anomaly_id}`}>View detail</Link>
      </td>
    </tr>
  );
}
