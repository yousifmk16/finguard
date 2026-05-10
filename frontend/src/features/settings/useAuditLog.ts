import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/features/auth/useAuth";
import { fetchAuditLogs } from "./audit-api";
import type { AuditLogListResponse, AuditLogQuery } from "./types";

export interface AuditLogState {
  data: AuditLogListResponse | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useAuditLog(query: AuditLogQuery = {}): AuditLogState {
  const { session, signOut } = useAuth();
  const token = session?.token ?? null;
  const [data, setData] = useState<AuditLogListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const queryKey = JSON.stringify(query);

  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();

    setLoading(true);
    setError(null);

    fetchAuditLogs(query, token, ctrl.signal)
      .then((res) => {
        if (!cancelled) {
          setData(res);
        }
      })
      .catch((err) => {
        if (cancelled || (err instanceof DOMException && err.name === "AbortError")) return;
        if (err instanceof ApiError) {
          if (err.status === 401) { signOut(); return; }
          if (err.status === 403) { setError("Admin access required for audit log."); return; }
          setError(err.detail || "Failed to load audit log.");
        } else {
          setError("Failed to load audit log.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; ctrl.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey, token, reloadKey, signOut]);

  return {
    data,
    loading,
    error,
    reload: () => setReloadKey((n) => n + 1),
  };
}
