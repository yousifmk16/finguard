export type AlertSeverity = "none" | "low" | "medium" | "high";
export type AlertStatus = "pending" | "sent" | "failed" | "suppressed";
export type AlertChannel = "in_app" | "email";

export interface AlertRecord {
  alert_id: string;
  anomaly_id: string;
  account_id: string;
  service: string;
  region: string;
  severity: AlertSeverity | string;
  channel: AlertChannel | string;
  status: AlertStatus | string;
  dedup_key: string;
  created_at: string;
  sent_at: string | null;
  error_detail: string | null;
}

export interface AlertListResponse {
  items: AlertRecord[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface AlertListQuery {
  page?: number;
  pageSize?: number;
  accountId?: string;
  service?: string;
  region?: string;
  severity?: AlertSeverity;
  status?: AlertStatus;
  channel?: AlertChannel;
}
