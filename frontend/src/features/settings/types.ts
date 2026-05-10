export interface AuditLogEntry {
  audit_id: string;
  event_type: string;
  action: string;
  outcome: string;
  user_id: string | null;
  actor_email: string | null;
  actor_role: string | null;
  target_type: string | null;
  target_id: string | null;
  ip_address: string | null;
  user_agent: string | null;
  meta: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditLogListResponse {
  items: AuditLogEntry[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface AuditLogQuery {
  page?: number;
  page_size?: number;
  event_type?: string;
  action?: string;
  outcome?: string;
}
