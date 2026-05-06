import { useCallback, useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Pagination from "@/components/common/Pagination";
import SeverityBadge from "@/components/common/SeverityBadge";
import StatusBadge from "@/components/common/StatusBadge";
import { formatDateTime, shortId } from "@/lib/formatters";
import AlertFilterBar, { type AlertFilters } from "./AlertFilterBar";
import { useAlertsList } from "./useAlertsList";
import type {
  AlertChannel,
  AlertListQuery,
  AlertRecord,
  AlertSeverity,
  AlertStatus,
} from "./types";

const DEFAULT_PAGE_SIZE = 25;
const MAX_PAGE_SIZE = 200;
// INT-02: how often to poll the alert list while the page is in the foreground.
const POLL_INTERVAL_MS = 15_000;

const SEVERITY_VALUES: AlertSeverity[] = ["none", "low", "medium", "high"];
const STATUS_VALUES: AlertStatus[] = ["pending", "sent", "failed", "suppressed"];
const CHANNEL_VALUES: AlertChannel[] = ["in_app", "email"];

function clampInt(
  value: string | null,
  fallback: number,
  min = 1,
  max = Number.MAX_SAFE_INTEGER,
): number {
  if (value === null) return fallback;
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) return fallback;
  return Math.min(Math.max(parsed, min), max);
}

function readFilters(params: URLSearchParams): AlertFilters {
  return {
    accountId: params.get("account_id") ?? "",
    service: params.get("service") ?? "",
    region: params.get("region") ?? "",
    severity: params.get("severity") ?? "",
    status: params.get("status") ?? "",
    channel: params.get("channel") ?? "",
  };
}

function narrowSeverity(value: string): AlertSeverity | undefined {
  return SEVERITY_VALUES.includes(value as AlertSeverity)
    ? (value as AlertSeverity)
    : undefined;
}

function narrowStatus(value: string): AlertStatus | undefined {
  return STATUS_VALUES.includes(value as AlertStatus)
    ? (value as AlertStatus)
    : undefined;
}

function narrowChannel(value: string): AlertChannel | undefined {
  return CHANNEL_VALUES.includes(value as AlertChannel)
    ? (value as AlertChannel)
    : undefined;
}

export default function AlertCenterPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = clampInt(searchParams.get("page"), 1, 1);
  const pageSize = clampInt(
    searchParams.get("page_size"),
    DEFAULT_PAGE_SIZE,
    1,
    MAX_PAGE_SIZE,
  );
  const filters = useMemo(() => readFilters(searchParams), [searchParams]);

  const query = useMemo<AlertListQuery>(
    () => ({
      page,
      pageSize,
      accountId: filters.accountId || undefined,
      service: filters.service || undefined,
      region: filters.region || undefined,
      severity: narrowSeverity(filters.severity),
      status: narrowStatus(filters.status),
      channel: narrowChannel(filters.channel),
    }),
    [page, pageSize, filters],
  );
  const { data, loading, error, reload, lastUpdatedAt } = useAlertsList(query, {
    pollIntervalMs: POLL_INTERVAL_MS,
  });

  const updateParams = useCallback(
    (
      mutate: (params: URLSearchParams) => void,
      { resetPage }: { resetPage: boolean } = { resetPage: false },
    ) => {
      const next = new URLSearchParams(searchParams);
      mutate(next);
      if (resetPage) next.delete("page");
      setSearchParams(next, { replace: false });
    },
    [searchParams, setSearchParams],
  );

  const handlePageChange = (nextPage: number) => {
    updateParams((params) => {
      params.set("page", String(nextPage));
      params.set("page_size", String(pageSize));
    });
  };

  const handleApplyFilters = (next: AlertFilters) => {
    updateParams((params) => {
      writeFilterParam(params, "account_id", next.accountId);
      writeFilterParam(params, "service", next.service);
      writeFilterParam(params, "region", next.region);
      writeFilterParam(params, "severity", next.severity);
      writeFilterParam(params, "status", next.status);
      writeFilterParam(params, "channel", next.channel);
    }, { resetPage: true });
  };

  const handleResetFilters = () => {
    updateParams((params) => {
      for (const key of ["account_id", "service", "region", "severity", "status", "channel"]) {
        params.delete(key);
      }
    }, { resetPage: true });
  };

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = data?.pages ?? 0;
  const showSkeleton = loading && data === null;
  const hasActiveFilters = Object.values(filters).some((v) => v !== "");

  return (
    <section className="anomalies-page">
      <header className="anomalies-page__header">
        <div>
          <h1>Alert Center</h1>
          <p className="anomalies-page__subtitle">
            Severity-grouped alert queue with delivery status across channels.
            <LiveIndicator lastUpdatedAt={lastUpdatedAt} />
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

      <AlertFilterBar
        filters={filters}
        onApply={handleApplyFilters}
        onReset={handleResetFilters}
        disabled={loading && data === null}
      />

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
              <th scope="col">Alert ID</th>
              <th scope="col">Anomaly</th>
              <th scope="col">Account</th>
              <th scope="col">Service</th>
              <th scope="col">Region</th>
              <th scope="col">Severity</th>
              <th scope="col">Channel</th>
              <th scope="col">Status</th>
              <th scope="col">Created</th>
              <th scope="col">Sent</th>
            </tr>
          </thead>
          <tbody>
            {showSkeleton ? (
              <tr>
                <td colSpan={10} className="data-table__placeholder">
                  Loading alerts...
                </td>
              </tr>
            ) : items.length === 0 && !error ? (
              <tr>
                <td colSpan={10} className="data-table__placeholder">
                  {hasActiveFilters
                    ? "No alerts match the current filters."
                    : "No alerts have been delivered yet."}
                </td>
              </tr>
            ) : (
              items.map((row) => <AlertRow key={row.alert_id} row={row} />)
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

function writeFilterParam(
  params: URLSearchParams,
  key: string,
  value: string,
): void {
  if (value) {
    params.set(key, value);
  } else {
    params.delete(key);
  }
}

function LiveIndicator({ lastUpdatedAt }: { lastUpdatedAt: number | null }) {
  if (lastUpdatedAt === null) return null;
  return (
    <span
      className="live-indicator"
      title={`Last refreshed ${new Date(lastUpdatedAt).toLocaleTimeString()} — auto-updates every 15s`}
    >
      <span className="live-indicator__dot" aria-hidden="true" />
      Live
    </span>
  );
}

function AlertRow({ row }: { row: AlertRecord }) {
  return (
    <tr>
      <td title={row.alert_id}>{shortId(row.alert_id)}</td>
      <td>
        <Link to={`/anomalies/${row.anomaly_id}`} title={row.anomaly_id}>
          {shortId(row.anomaly_id)}
        </Link>
      </td>
      <td>{row.account_id}</td>
      <td>{row.service}</td>
      <td>{row.region}</td>
      <td>
        <SeverityBadge severity={row.severity} />
      </td>
      <td>
        <span className="badge badge--channel">{row.channel.replace("_", "-")}</span>
      </td>
      <td>
        <StatusBadge status={row.status} />
        {row.status === "failed" && row.error_detail ? (
          <span
            className="alert-error"
            title={row.error_detail}
            aria-label={`Failure reason: ${row.error_detail}`}
          >
            {" "}!
          </span>
        ) : null}
      </td>
      <td>{formatDateTime(row.created_at)}</td>
      <td>{formatDateTime(row.sent_at)}</td>
    </tr>
  );
}
