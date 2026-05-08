import { useCallback, useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Pagination from "@/components/common/Pagination";
import SeverityBadge from "@/components/common/SeverityBadge";
import StatusBadge from "@/components/common/StatusBadge";
import { formatDateTime, formatScore, shortId } from "@/lib/formatters";
import AnomalyFilterBar, {
  type AnomalyFilters,
} from "./AnomalyFilterBar";
import { useAnomaliesList } from "./useAnomaliesList";
import type {
  AnomalyListQuery,
  AnomalyRecord,
  AnomalySeverity,
  AnomalySortField,
  AnomalySortOrder,
  AnomalyStatus,
} from "./types";

const DEFAULT_PAGE_SIZE = 25;
const MAX_PAGE_SIZE = 200;
const DEFAULT_SORT: AnomalySortField = "detected_at";
const DEFAULT_ORDER: AnomalySortOrder = "desc";

const SORT_FIELDS: AnomalySortField[] = [
  "detected_at",
  "bucket",
  "anomaly_score",
  "severity",
];

const SEVERITY_VALUES: AnomalySeverity[] = ["none", "low", "medium", "high"];
const STATUS_VALUES: AnomalyStatus[] = [
  "open",
  "acknowledged",
  "resolved",
  "suppressed",
];

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

function readSort(value: string | null): AnomalySortField {
  return SORT_FIELDS.includes(value as AnomalySortField)
    ? (value as AnomalySortField)
    : DEFAULT_SORT;
}

function readOrder(value: string | null): AnomalySortOrder {
  return value === "asc" ? "asc" : DEFAULT_ORDER;
}

function readFilters(params: URLSearchParams): AnomalyFilters {
  return {
    accountId: params.get("account_id") ?? "",
    service: params.get("service") ?? "",
    region: params.get("region") ?? "",
    severity: params.get("severity") ?? "",
    status: params.get("status") ?? "",
    fromBucket: params.get("from_bucket") ?? "",
    toBucket: params.get("to_bucket") ?? "",
  };
}

// Severity / status come from the URL as raw strings; only forward them to the
// API when they match the typed enums so a tampered URL never produces a 422.
function narrowSeverity(value: string): AnomalySeverity | undefined {
  return SEVERITY_VALUES.includes(value as AnomalySeverity)
    ? (value as AnomalySeverity)
    : undefined;
}

function narrowStatus(value: string): AnomalyStatus | undefined {
  return STATUS_VALUES.includes(value as AnomalyStatus)
    ? (value as AnomalyStatus)
    : undefined;
}

export default function AnomaliesListPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const page = clampInt(searchParams.get("page"), 1, 1);
  const pageSize = clampInt(
    searchParams.get("page_size"),
    DEFAULT_PAGE_SIZE,
    1,
    MAX_PAGE_SIZE,
  );
  const sort = readSort(searchParams.get("sort"));
  const order = readOrder(searchParams.get("order"));
  const filters = useMemo(() => readFilters(searchParams), [searchParams]);

  const query = useMemo<AnomalyListQuery>(
    () => ({
      page,
      pageSize,
      sort,
      order,
      accountId: filters.accountId || undefined,
      service: filters.service || undefined,
      region: filters.region || undefined,
      severity: narrowSeverity(filters.severity),
      status: narrowStatus(filters.status),
      fromBucket: filters.fromBucket || undefined,
      toBucket: filters.toBucket || undefined,
    }),
    [page, pageSize, sort, order, filters],
  );
  const { data, loading, error, reload } = useAnomaliesList(query);

  // When filters or sort change, jump back to page 1; preserving page would
  // often land users on an empty page they did not ask for.
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

  const handleApplyFilters = (next: AnomalyFilters) => {
    updateParams((params) => {
      writeFilterParam(params, "account_id", next.accountId);
      writeFilterParam(params, "service", next.service);
      writeFilterParam(params, "region", next.region);
      writeFilterParam(params, "severity", next.severity);
      writeFilterParam(params, "status", next.status);
      writeFilterParam(params, "from_bucket", next.fromBucket);
      writeFilterParam(params, "to_bucket", next.toBucket);
    }, { resetPage: true });
  };

  const handleResetFilters = () => {
    updateParams((params) => {
      for (const key of [
        "account_id",
        "service",
        "region",
        "severity",
        "status",
        "from_bucket",
        "to_bucket",
      ]) {
        params.delete(key);
      }
    }, { resetPage: true });
  };

  const handleSort = (field: AnomalySortField) => {
    updateParams((params) => {
      const isSame = sort === field;
      const nextOrder: AnomalySortOrder = isSame && order === "desc" ? "asc" : "desc";
      params.set("sort", field);
      params.set("order", nextOrder);
    }, { resetPage: true });
  };

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = data?.pages ?? 0;
  const showSkeleton = loading && data === null;
  const hasActiveFilters =
    Object.values(filters).some((value) => value !== "") ||
    sort !== DEFAULT_SORT ||
    order !== DEFAULT_ORDER;

  return (
    <section className="anomalies-page" aria-labelledby="anomalies-heading">
      <header className="anomalies-page__header">
        <div>
          <h1 id="anomalies-heading">Anomalies</h1>
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

      <AnomalyFilterBar
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
              <th scope="col">ID</th>
              <th scope="col">Account</th>
              <th scope="col" className="data-table__col--hide-sm">Service</th>
              <th scope="col" className="data-table__col--hide-md">Region</th>
              <SortHeader
                label="Score"
                field="anomaly_score"
                currentSort={sort}
                currentOrder={order}
                onSort={handleSort}
                className="data-table__col-num"
              />
              <SortHeader
                label="Severity"
                field="severity"
                currentSort={sort}
                currentOrder={order}
                onSort={handleSort}
              />
              <th scope="col">Status</th>
              <SortHeader
                label="Detected"
                field="detected_at"
                currentSort={sort}
                currentOrder={order}
                onSort={handleSort}
                className="data-table__col--hide-md"
              />
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
                  {hasActiveFilters
                    ? "No anomalies match the current filters."
                    : "No anomalies match the current view."}
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

interface SortHeaderProps {
  label: string;
  field: AnomalySortField;
  currentSort: AnomalySortField;
  currentOrder: AnomalySortOrder;
  onSort: (field: AnomalySortField) => void;
  className?: string;
}

function SortHeader({
  label,
  field,
  currentSort,
  currentOrder,
  onSort,
  className,
}: SortHeaderProps) {
  const active = currentSort === field;
  const ariaSort = active
    ? currentOrder === "asc"
      ? "ascending"
      : "descending"
    : "none";
  const indicator = active ? (currentOrder === "asc" ? "▲" : "▼") : "";

  return (
    <th scope="col" className={className} aria-sort={ariaSort}>
      <button
        type="button"
        className={`data-table__sort${active ? " data-table__sort--active" : ""}`}
        onClick={() => onSort(field)}
      >
        <span>{label}</span>
        <span className="data-table__sort-indicator" aria-hidden="true">
          {indicator}
        </span>
      </button>
    </th>
  );
}

function AnomalyRow({ row }: { row: AnomalyRecord }) {
  return (
    <tr>
      <td>
        <Link
          to={`/anomalies/${row.anomaly_id}`}
          title={row.anomaly_id}
          aria-label={`Anomaly ${shortId(row.anomaly_id)}`}
        >
          {shortId(row.anomaly_id)}
        </Link>
      </td>
      <td>{row.account_id}</td>
      <td className="data-table__col--hide-sm">{row.service}</td>
      <td className="data-table__col--hide-md">{row.region}</td>
      <td className="data-table__col-num">{formatScore(row.anomaly_score)}</td>
      <td>
        <SeverityBadge severity={row.severity} />
      </td>
      <td>
        <StatusBadge status={row.status} />
      </td>
      <td className="data-table__col--hide-md">{formatDateTime(row.detected_at)}</td>
      <td className="data-table__col-action">
        <Link
          to={`/anomalies/${row.anomaly_id}`}
          aria-label={`View detail for anomaly ${shortId(row.anomaly_id)}`}
        >
          View detail
        </Link>
      </td>
    </tr>
  );
}
