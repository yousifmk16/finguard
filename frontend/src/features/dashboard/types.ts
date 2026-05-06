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
