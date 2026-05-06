import { apiFetch } from "@/lib/api";
import type { AnomalyListQuery, AnomalyListResponse, AnomalyRecord } from "./types";

function buildQueryString(query: AnomalyListQuery): string {
  const params = new URLSearchParams();
  if (query.page !== undefined) params.set("page", String(query.page));
  if (query.pageSize !== undefined) params.set("page_size", String(query.pageSize));
  if (query.accountId) params.set("account_id", query.accountId);
  if (query.service) params.set("service", query.service);
  if (query.region) params.set("region", query.region);
  if (query.severity) params.set("severity", query.severity);
  if (query.status) params.set("status", query.status);
  if (query.fromBucket) params.set("from_bucket", query.fromBucket);
  if (query.toBucket) params.set("to_bucket", query.toBucket);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function listAnomalies(
  query: AnomalyListQuery,
  token: string | null,
  signal?: AbortSignal,
): Promise<AnomalyListResponse> {
  return apiFetch<AnomalyListResponse>(`/anomalies${buildQueryString(query)}`, {
    token,
    signal,
  });
}

export function getAnomaly(
  anomalyId: string,
  token: string | null,
  signal?: AbortSignal,
): Promise<AnomalyRecord> {
  return apiFetch<AnomalyRecord>(`/anomalies/${anomalyId}`, { token, signal });
}
