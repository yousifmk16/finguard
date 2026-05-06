import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/features/auth/useAuth";
import { getKpiSummary, getKpiTrend } from "./kpi-api";
import type { KpiSummary, KpiTrend } from "./types";

interface State<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

function mapError(err: unknown, signOut: () => void): string | null {
  if (err instanceof DOMException && err.name === "AbortError") return null;
  if (err instanceof ApiError) {
    if (err.status === 401) {
      signOut();
      return null;
    }
    if (err.status === 403) return "You do not have permission to view dashboard data.";
    if (err.status === 0) return "Could not reach the server. Check your connection.";
    return err.detail || "Failed to load dashboard data.";
  }
  return "Failed to load dashboard data.";
}

export function useKpiSummary(): State<KpiSummary> {
  const { session, signOut } = useAuth();
  const token = session?.token ?? null;
  const [data, setData] = useState<KpiSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);

    getKpiSummary(token, controller.signal)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((err) => {
        if (cancelled) return;
        const msg = mapError(err, signOut);
        if (msg !== null) setError(msg);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [token, reloadKey, signOut]);

  return { data, loading, error, reload: () => setReloadKey((n) => n + 1) };
}

export function useKpiTrend(days: number): State<KpiTrend> {
  const { session, signOut } = useAuth();
  const token = session?.token ?? null;
  const [data, setData] = useState<KpiTrend | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);

    getKpiTrend(days, token, controller.signal)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((err) => {
        if (cancelled) return;
        const msg = mapError(err, signOut);
        if (msg !== null) setError(msg);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [days, token, reloadKey, signOut]);

  return { data, loading, error, reload: () => setReloadKey((n) => n + 1) };
}
