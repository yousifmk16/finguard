import { apiFetch } from "@/lib/api";
import type { PipelineHealth } from "./types";

export function getDetectionHealth(
  token: string | null,
  signal?: AbortSignal,
): Promise<PipelineHealth> {
  return apiFetch<PipelineHealth>(`/detection/health`, { token, signal });
}
