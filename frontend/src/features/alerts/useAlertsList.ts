import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/features/auth/useAuth";
import { listAlerts } from "./alerts-api";
import type { AlertListQuery, AlertListResponse } from "./types";

export interface AlertsListState {
  data: AlertListResponse | null;
  loading: boolean;
  error: string | null;
  /** Wall-clock time (ms) of the most recent successful refresh. */
  lastUpdatedAt: number | null;
  reload: () => void;
}

export interface AlertsListOptions {
  /**
   * INT-02: When set, the hook polls the API every ``pollIntervalMs`` ms
   * for live updates. Polling pauses while ``document.hidden`` is true and
   * resumes (with an immediate refetch) when the tab regains focus.
   */
  pollIntervalMs?: number;
}

export function useAlertsList(
  query: AlertListQuery,
  options: AlertsListOptions = {},
): AlertsListState {
  const { session, signOut } = useAuth();
  const token = session?.token ?? null;
  const [data, setData] = useState<AlertListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const queryKey = JSON.stringify(query);
  const pollIntervalMs = options.pollIntervalMs;

  useEffect(() => {
    let cancelled = false;
    let inFlight: AbortController | null = null;
    let timer: number | undefined;

    const handleError = (err: unknown) => {
      if (cancelled || (err instanceof DOMException && err.name === "AbortError")) return;
      if (err instanceof ApiError) {
        if (err.status === 401) {
          signOut();
          return;
        }
        if (err.status === 403) {
          setError("You do not have permission to view alerts.");
        } else if (err.status === 0) {
          setError("Could not reach the server. Check your connection.");
        } else {
          setError(err.detail || "Failed to load alerts.");
        }
      } else {
        setError("Failed to load alerts.");
      }
    };

    const fetchOnce = ({ silent }: { silent: boolean }) => {
      if (cancelled) return;
      inFlight?.abort();
      inFlight = new AbortController();
      // Foreground load shows the spinner; poll-driven refreshes don't,
      // so the table doesn't blink every interval.
      if (!silent) setLoading(true);
      if (!silent) setError(null);

      listAlerts(query, token, inFlight.signal)
        .then((response) => {
          if (cancelled) return;
          setData(response);
          setLastUpdatedAt(Date.now());
          if (silent) setError(null);
        })
        .catch(handleError)
        .finally(() => {
          if (!cancelled && !silent) setLoading(false);
        });
    };

    const startPolling = () => {
      if (!pollIntervalMs || timer !== undefined) return;
      timer = window.setInterval(() => fetchOnce({ silent: true }), pollIntervalMs);
    };

    const stopPolling = () => {
      if (timer !== undefined) {
        window.clearInterval(timer);
        timer = undefined;
      }
    };

    const handleVisibility = () => {
      if (document.hidden) {
        stopPolling();
      } else {
        // Catch up immediately, then resume the cadence.
        fetchOnce({ silent: data !== null });
        startPolling();
      }
    };

    fetchOnce({ silent: false });
    if (pollIntervalMs && !document.hidden) startPolling();
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", handleVisibility);
      stopPolling();
      inFlight?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey, token, reloadKey, signOut, pollIntervalMs]);

  return {
    data,
    loading,
    error,
    lastUpdatedAt,
    reload: () => setReloadKey((n) => n + 1),
  };
}
