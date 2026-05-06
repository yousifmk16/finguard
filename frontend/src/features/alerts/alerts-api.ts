import { apiFetch } from "@/lib/api";
import type { AlertListQuery, AlertListResponse } from "./types";

function buildQueryString(query: AlertListQuery): string {
  const params = new URLSearchParams();
  if (query.page !== undefined) params.set("page", String(query.page));
  if (query.pageSize !== undefined) params.set("page_size", String(query.pageSize));
  if (query.accountId) params.set("account_id", query.accountId);
  if (query.service) params.set("service", query.service);
  if (query.region) params.set("region", query.region);
  if (query.severity) params.set("severity", query.severity);
  if (query.status) params.set("status", query.status);
  if (query.channel) params.set("channel", query.channel);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export function listAlerts(
  query: AlertListQuery,
  token: string | null,
  signal?: AbortSignal,
): Promise<AlertListResponse> {
  return apiFetch<AlertListResponse>(`/alerts${buildQueryString(query)}`, {
    token,
    signal,
  });
}
