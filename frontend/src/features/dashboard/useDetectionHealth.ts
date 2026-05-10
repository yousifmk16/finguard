import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/features/auth/useAuth";
import { getDetectionHealth } from "./pipeline-api";
import type { PipelineHealth } from "./types";

interface State {
  data: PipelineHealth | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useDetectionHealth(): State {
  const { session, signOut } = useAuth();
  const token = session?.token ?? null;
  const [data, setData] = useState<PipelineHealth | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);

    getDetectionHealth(token, controller.signal)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (err instanceof ApiError) {
          if (err.status === 401) { signOut(); return; }
          setError(err.detail || "Failed to load pipeline health.");
        } else {
          setError("Failed to load pipeline health.");
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
