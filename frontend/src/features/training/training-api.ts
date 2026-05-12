import { apiFetch } from "@/lib/api";
import { API_BASE_URL } from "@/lib/env";

export interface ModelArtifactStatus {
  trained: boolean;
  last_trained_at: string | null;
  version: string | null;
  train_rows: number;
  artifact_dir: string;
  extra: Record<string, unknown>;
}

export interface DataStats {
  generated: number;
  uploaded: number;
  total: number;
}

export interface TrainingStatusResponse {
  baseline: ModelArtifactStatus;
  autoencoder: ModelArtifactStatus;
  data: DataStats;
}

export interface TrainRequest {
  lookback_days: number;
  min_train_rows: number;
  data_source: string;
  profile_id?: string;  // if set, train into this profile without changing the active inference model
}

export interface TrainResult {
  model: string;
  train_rows: number;
  elapsed_seconds: number;
  artifact_dir: string;
  version: string | null;
}

export interface UploadResult {
  accepted: number;
  failed: number;
  total: number;
  errors: string[];
}

export function getTrainingStatus(
  token: string | null,
  signal?: AbortSignal,
): Promise<TrainingStatusResponse> {
  return apiFetch<TrainingStatusResponse>("/admin/train/status", { token, signal });
}

export function trainBaseline(
  body: TrainRequest,
  token: string | null,
  signal?: AbortSignal,
): Promise<TrainResult> {
  return apiFetch<TrainResult>("/admin/train/baseline", {
    method: "POST",
    body,
    token,
    signal,
  });
}

export function trainAutoencoder(
  body: TrainRequest,
  token: string | null,
  signal?: AbortSignal,
): Promise<TrainResult> {
  return apiFetch<TrainResult>("/admin/train/autoencoder", {
    method: "POST",
    body,
    token,
    signal,
  });
}

export interface TrainingRow {
  timestamp: string;
  provider: string;
  account_id: string;
  service: string;
  region: string;
  cost_amount: number;
  usage_amount: number;
  usage_unit: string;
  source: "generated" | "uploaded";
}

export interface TrainingDataPage {
  rows: TrainingRow[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export function getTrainingData(
  params: { page?: number; page_size?: number; source?: string },
  token: string | null,
  signal?: AbortSignal,
): Promise<TrainingDataPage> {
  const qs = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.page_size ?? 50),
    source: params.source ?? "all",
  });
  return apiFetch<TrainingDataPage>(`/admin/train/data?${qs}`, { token, signal });
}

export async function uploadTrainingData(
  file: File,
  token: string | null,
): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);

  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const url = `${API_BASE_URL}/admin/train/data/upload`.replace(/([^:])\/\//g, "$1/");
  const res = await fetch(url, { method: "POST", headers, body: form });

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    const detail =
      payload?.detail ?? res.statusText ?? `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Profile management
// ---------------------------------------------------------------------------

export interface FinGuardProfile {
  id: string;
  name: string;
  created_at: string;
  active: boolean;
  baseline: ModelArtifactStatus;
  autoencoder: ModelArtifactStatus;
}

export interface ProfilesResponse {
  profiles: FinGuardProfile[];
  active_id: string | null;
}

export function listProfiles(token: string | null): Promise<ProfilesResponse> {
  return apiFetch<ProfilesResponse>("/admin/train/profiles", { token });
}

export function createProfile(name: string, token: string | null): Promise<FinGuardProfile> {
  return apiFetch<FinGuardProfile>("/admin/train/profiles", {
    method: "POST",
    body: { name },
    token,
  });
}

export function renameProfile(id: string, name: string, token: string | null): Promise<FinGuardProfile> {
  return apiFetch<FinGuardProfile>(`/admin/train/profiles/${id}`, {
    method: "PATCH",
    body: { name },
    token,
  });
}

export function activateProfile(id: string, token: string | null): Promise<ProfilesResponse> {
  return apiFetch<ProfilesResponse>(`/admin/train/profiles/${id}/activate`, {
    method: "POST",
    token,
  });
}

export function deleteProfile(id: string, token: string | null): Promise<ProfilesResponse> {
  return apiFetch<ProfilesResponse>(`/admin/train/profiles/${id}`, {
    method: "DELETE",
    token,
  });
}

export async function exportTrainingData(token: string | null): Promise<void> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;

  const url = `${API_BASE_URL}/admin/train/data/export`.replace(/([^:])\/\//g, "$1/");
  const res = await fetch(url, { headers });

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    const detail =
      payload?.detail ?? res.statusText ?? `HTTP ${res.status}`;
    throw new Error(detail);
  }

  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "training_data.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}
