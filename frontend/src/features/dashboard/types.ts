export interface ServiceCount {
  service: string;
  count: number;
}

export interface AccountCount {
  account_id: string;
  count: number;
}

export interface KpiSummary {
  total_anomalies: number;
  open_count: number;
  acknowledged_count: number;
  resolved_count: number;
  suppressed_count: number;
  high_severity_count: number;
  medium_severity_count: number;
  low_severity_count: number;
  anomalies_last_24h: number;
  daily_avg: number;
  mtt_ack_p50_seconds: number | null;
  mtt_ack_p95_seconds: number | null;
  top_services: ServiceCount[];
  top_accounts: AccountCount[];
}

export interface TrendPoint {
  day: string;
  count: number;
}

export interface KpiTrend {
  days: number;
  points: TrendPoint[];
}

export interface PipelineComponentStatus {
  status: string;
  detail?: string;
  // scorer
  baseline_loaded?: boolean;
  if_loaded?: boolean;
  config?: Record<string, unknown>;
  // emitter
  stream_name?: string;
  include_breakdown?: boolean;
}

export interface DetectionMetrics {
  batches_processed: number;
  rows_scored: number;
  anomalies_detected: number;
  anomalies_persisted: number;
  events_emitted: number;
  errors_scoring: number;
  errors_persist: number;
  errors_emit: number;
  last_batch_at: string | null;
  last_batch_rows: number;
  last_batch_anomalies: number;
}

export interface PipelineHealth {
  status: "ok" | "degraded";
  components: {
    db: PipelineComponentStatus;
    scorer: PipelineComponentStatus;
    emitter: PipelineComponentStatus;
  };
  metrics: DetectionMetrics;
  lag_p95_ms: number | null;
}
