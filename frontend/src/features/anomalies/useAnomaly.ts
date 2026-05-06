import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/features/auth/useAuth";
import { getAnomaly, updateAnomalyStatus } from "./anomalies-api";
import type { AnomalyRecord, AnomalyStatus } from "./types";

export interface AnomalyDetailState {
  data: AnomalyRecord | null;
  loading: boolean;
  error: string | null;
  notFound: boolean;
  reload: () => void;
  /**
   * UI-08: Mutate the anomaly's lifecycle status.
   * Optimistically updates the cached record so the badge flips immediately;
   * on failure the previous status is restored and ``mutationError`` is set.
   * Returns the updated record on success or null on failure.
   */
  updateStatus: (status: AnomalyStatus) => Promise<AnomalyRecord | null>;
  mutating: boolean;
  mutationError: string | null;
  clearMutationError: () => void;
}

export function useAnomaly(anomalyId: string | undefined): AnomalyDetailState {
  const { session, signOut } = useAuth();
  const token = session?.token ?? null;
  const [data, setData] = useState<AnomalyRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [mutating, setMutating] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);

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

  const updateStatus = useCallback(
    async (nextStatus: AnomalyStatus): Promise<AnomalyRecord | null> => {
      if (!anomalyId || !data) return null;
      const previous = data;
      // Optimistic update so the UI feels instant; revert on failure.
      setData({ ...data, status: nextStatus });
      setMutating(true);
      setMutationError(null);

      try {
        const updated = await updateAnomalyStatus(anomalyId, nextStatus, token);
        setData(updated);
        return updated;
      } catch (err) {
        setData(previous);
        if (err instanceof ApiError) {
          if (err.status === 401) {
            signOut();
            return null;
          }
          if (err.status === 403) {
            setMutationError("You do not have permission to change anomaly status.");
          } else if (err.status === 404) {
            setMutationError("Anomaly was deleted or is no longer available.");
          } else if (err.status === 0) {
            setMutationError("Could not reach the server. Check your connection.");
          } else {
            setMutationError(err.detail || "Failed to update status.");
          }
        } else {
          setMutationError("Failed to update status.");
        }
        return null;
      } finally {
        setMutating(false);
      }
    },
    [anomalyId, data, token, signOut],
  );

  return {
    data,
    loading,
    error,
    notFound,
    reload: () => setReloadKey((n) => n + 1),
    updateStatus,
    mutating,
    mutationError,
    clearMutationError: () => setMutationError(null),
  };
}
