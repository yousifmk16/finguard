import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/features/auth/useAuth";
import { listAnomalies } from "./anomalies-api";
import type { AnomalyListQuery, AnomalyListResponse } from "./types";

export interface AnomaliesListState {
  data: AnomalyListResponse | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useAnomaliesList(query: AnomalyListQuery): AnomaliesListState {
  const { session, signOut } = useAuth();
  const token = session?.token ?? null;
  const [data, setData] = useState<AnomalyListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Stringify the query so the effect re-runs only on real value changes,
  // not on every parent render that recreates the object identity.
  const queryKey = JSON.stringify(query);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);

    listAnomalies(query, token, controller.signal)
      .then((response) => {
        if (cancelled) return;
        setData(response);
      })
      .catch((err: unknown) => {
        if (cancelled || (err instanceof DOMException && err.name === "AbortError")) return;
        if (err instanceof ApiError) {
          if (err.status === 401) {
            signOut();
            return;
          }
          if (err.status === 403) {
            setError("You do not have permission to view anomalies.");
          } else if (err.status === 0) {
            setError("Could not reach the server. Check your connection.");
          } else {
            setError(err.detail || "Failed to load anomalies.");
          }
        } else {
          setError("Failed to load anomalies.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey, token, reloadKey, signOut]);

  return {
    data,
    loading,
    error,
    reload: () => setReloadKey((n) => n + 1),
  };
}
