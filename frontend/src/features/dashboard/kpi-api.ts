import { apiFetch } from "@/lib/api";
import type { KpiSummary, KpiTrend } from "./types";

export function getKpiSummary(
  token: string | null,
  signal?: AbortSignal,
): Promise<KpiSummary> {
  return apiFetch<KpiSummary>(`/kpi/summary`, { token, signal });
}

export function getKpiTrend(
  days: number,
  token: string | null,
  signal?: AbortSignal,
): Promise<KpiTrend> {
  return apiFetch<KpiTrend>(`/kpi/trend?days=${days}`, { token, signal });
}
