import { apiFetch } from "@/lib/api";

export interface ConnectionStatus {
  provider: string;
  connected: boolean;
  region?: string | null;
  project_id?: string | null;
  masked_key?: string | null;
}

export interface ConnectionsResponse {
  aws: ConnectionStatus;
  gcp: ConnectionStatus;
}

export interface AWSCredentials {
  access_key_id: string;
  secret_access_key: string;
  region: string;
}

export interface GCPCredentials {
  project_id: string;
  service_account_json: string;
}

export const fetchConnections = (token: string) =>
  apiFetch<ConnectionsResponse>("/settings/connections", { token });

export const saveAWS = (creds: AWSCredentials, token: string) =>
  apiFetch<ConnectionStatus>("/settings/connections/aws", { method: "PUT", body: creds, token });

export const saveGCP = (creds: GCPCredentials, token: string) =>
  apiFetch<ConnectionStatus>("/settings/connections/gcp", { method: "PUT", body: creds, token });

export const removeConnection = (provider: "aws" | "gcp", token: string) =>
  apiFetch<ConnectionStatus>(`/settings/connections/${provider}`, { method: "DELETE", token });
