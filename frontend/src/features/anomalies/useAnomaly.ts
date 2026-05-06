import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/features/auth/useAuth";
import { getAnomaly } from "./anomalies-api";
import type { AnomalyRecord } from "./types";

export interface AnomalyDetailState {
  data: AnomalyRecord | null;
  loading: boolean;
  error: string | null;
  notFound: boolean;
  reload: () => void;
}

export function useAnomaly(anomalyId: string | undefined): AnomalyDetailState {
  const { session, signOut } = useAuth();
  const token = session?.token ?? null;
  const [data, setData] = useState<AnomalyRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!anomalyId) {
      setData(null);
      setError("Missing anomaly id");
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);
    setNotFound(false);

    getAnomaly(anomalyId, token, controller.signal)
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
            setError("You do not have permission to view this anomaly.");
          } else if (err.status === 404) {
            setNotFound(true);
          } else if (err.status === 0) {
            setError("Could not reach the server. Check your connection.");
          } else {
            setError(err.detail || "Failed to load anomaly.");
          }
          setData(null);
        } else {
          setError("Failed to load anomaly.");
          setData(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [anomalyId, token, reloadKey, signOut]);

  return {
    data,
    loading,
    error,
    notFound,
    reload: () => setReloadKey((n) => n + 1),
  };
}
