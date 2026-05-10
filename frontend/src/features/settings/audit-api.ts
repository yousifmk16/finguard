import { apiFetch } from "@/lib/api";
import type { AuditLogListResponse, AuditLogQuery } from "./types";

export function fetchAuditLogs(
  query: AuditLogQuery,
  token: string | null,
  signal?: AbortSignal,
): Promise<AuditLogListResponse> {
  const params = new URLSearchParams();
  if (query.page) params.set("page", String(query.page));
  if (query.page_size) params.set("page_size", String(query.page_size));
  if (query.event_type) params.set("event_type", query.event_type);
  if (query.action) params.set("action", query.action);
  if (query.outcome) params.set("outcome", query.outcome);

  const qs = params.toString();
  return apiFetch<AuditLogListResponse>(
    `/audit/logs${qs ? `?${qs}` : ""}`,
    { token, signal },
  );
}
