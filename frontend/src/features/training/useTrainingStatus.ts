import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/features/auth/useAuth";
import { getTrainingStatus } from "./training-api";
import type { TrainingStatusResponse } from "./training-api";

interface State {
  data: TrainingStatusResponse | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useTrainingStatus(): State {
  const { session, signOut } = useAuth();
  const token = session?.token ?? null;
  const [data, setData] = useState<TrainingStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);

    getTrainingStatus(token, controller.signal)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (err instanceof ApiError) {
          if (err.status === 401) { signOut(); return; }
          setError(err.detail || "Failed to load training status.");
        } else {
          setError("Failed to load training status.");
        }
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
