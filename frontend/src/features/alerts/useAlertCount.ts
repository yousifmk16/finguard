import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/features/auth/useAuth";
import { listAlerts } from "./alerts-api";

const DEFAULT_INTERVAL_MS = 30_000;

export interface AlertCountState {
  pending: number;
  /** True while the very first fetch is in flight (no count to show yet). */
  loading: boolean;
  /** True iff the last polling fetch failed. The previous count is preserved. */
  stale: boolean;
}

/**
 * INT-02: Periodically polls the alert API for the count of ``pending`` alerts.
 *
 * Pauses while the tab is hidden so a backgrounded dashboard doesn't keep
 * hammering the API, and refetches immediately when the user returns to the
 * tab (so the badge "feels live" after switching back in).
 */
export function useAlertCount(intervalMs: number = DEFAULT_INTERVAL_MS): AlertCountState {
  const { session, signOut } = useAuth();
  const token = session?.token ?? null;
  const [pending, setPending] = useState(0);
  const [loading, setLoading] = useState(true);
  const [stale, setStale] = useState(false);

  useEffect(() => {
    if (!token) {
      setPending(0);
      setLoading(false);
      setStale(false);
      return;
    }

    let cancelled = false;
    let timer: number | undefined;
    let inFlight: AbortController | null = null;

    const fetchOnce = () => {
      if (cancelled) return;
      // Cancel any prior in-flight request so a slow network can't race a
      // fresher poll. We only ever care about the latest count.
      inFlight?.abort();
      inFlight = new AbortController();
      // page_size=1 keeps the payload tiny — we only need ``total``.
      listAlerts({ status: "pending", page: 1, pageSize: 1 }, token, inFlight.signal)
        .then((response) => {
          if (cancelled) return;
          setPending(response.total);
          setLoading(false);
          setStale(false);
        })
        .catch((err: unknown) => {
          if (cancelled || (err instanceof DOMException && err.name === "AbortError")) return;
          // 401 means the token expired — let the auth context redirect.
          if (err instanceof ApiError && err.status === 401) {
            signOut();
            return;
          }
          // For other failures, keep the last known count and mark it stale
          // so the UI can show a subtle warning instead of going to zero.
          setStale(true);
          setLoading(false);
        });
    };

    const start = () => {
      fetchOnce();
      timer = window.setInterval(fetchOnce, intervalMs);
    };

    const stop = () => {
      if (timer !== undefined) {
        window.clearInterval(timer);
        timer = undefined;
      }
      inFlight?.abort();
    };

    const handleVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        start();
      }
    };

    if (!document.hidden) start();
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", handleVisibility);
      stop();
    };
  }, [token, intervalMs, signOut]);

  return { pending, loading, stale };
}
