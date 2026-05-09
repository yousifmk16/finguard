import { API_BASE_URL } from "./env";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly payload: unknown;

  constructor(status: number, detail: string, payload?: unknown) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.payload = payload;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  token?: string | null;
  signal?: AbortSignal;
}

function joinUrl(base: string, path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  if (!base.endsWith("/") && !path.startsWith("/")) return `${base}/${path}`;
  if (base.endsWith("/") && path.startsWith("/")) return `${base}${path.slice(1)}`;
  return `${base}${path}`;
}

function extractDetail(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object") {
    // Standard FastAPI format: { detail: string | [{msg: string}] }
    if ("detail" in payload) {
      const detail = (payload as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail) && detail.length > 0) {
        const first = detail[0];
        if (first && typeof first === "object" && "msg" in first) {
          const msg = (first as { msg?: unknown }).msg;
          if (typeof msg === "string") return msg;
        }
      }
    }
    // Custom FinGuard validation format: { errors: [{field, message}] }
    if ("errors" in payload) {
      const errors = (payload as { errors?: unknown }).errors;
      if (Array.isArray(errors) && errors.length > 0) {
        const first = errors[0];
        if (first && typeof first === "object" && "message" in first) {
          const msg = (first as { message?: unknown }).message;
          if (typeof msg === "string") return msg;
        }
      }
    }
  }
  return fallback;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, token, signal } = options;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(joinUrl(API_BASE_URL, path), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "Network request failed", err);
  }

  const isJson = response.headers.get("content-type")?.includes("application/json") ?? false;
  const payload = isJson ? await response.json().catch(() => null) : await response.text().catch(() => null);

  if (!response.ok) {
    const detail = extractDetail(payload, response.statusText || `HTTP ${response.status}`);
    throw new ApiError(response.status, detail, payload);
  }
  return payload as T;
}
