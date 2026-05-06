export type AnomalySeverity = "none" | "low" | "medium" | "high";
export type AnomalyStatus = "open" | "acknowledged" | "resolved" | "suppressed";

export interface AnomalyRecord {
  anomaly_id: string;
  account_id: string;
  service: string;
  region: string;
  bucket: string;
  anomaly_score: number;
  severity: AnomalySeverity | string;
  status: AnomalyStatus | string;
  detected_at: string;
  score_breakdown?: Record<string, unknown> | null;
}

export interface AnomalyListResponse {
  items: AnomalyRecord[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export type AnomalySortField = "detected_at" | "bucket" | "anomaly_score" | "severity";
export type AnomalySortOrder = "asc" | "desc";

export interface AnomalyListQuery {
  page?: number;
  pageSize?: number;
  accountId?: string;
  service?: string;
  region?: string;
  severity?: AnomalySeverity;
  status?: AnomalyStatus;
  fromBucket?: string;
  toBucket?: string;
  sort?: AnomalySortField;
  order?: AnomalySortOrder;
}
