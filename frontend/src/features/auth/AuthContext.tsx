import { createContext, useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { decodeJwtPayload } from "@/lib/jwt";
import { loginRequest } from "./auth-api";

export type UserRole = "admin" | "analyst";

export interface AuthUser {
  userId: string;
  email: string;
  role: UserRole;
}

export interface AuthSession {
  token: string;
  /** Epoch milliseconds at which `token` expires. */
  expiresAt: number;
  user: AuthUser;
}

export interface AuthContextValue {
  session: AuthSession | null;
  isAuthenticated: boolean;
  signIn: (email: string, password: string, signal?: AbortSignal) => Promise<AuthSession>;
  signOut: () => void;
}

const STORAGE_KEY = "finguard.auth.session";
const EXPIRY_GRACE_MS = 5_000;

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function isExpired(session: AuthSession | null): boolean {
  if (!session) return false;
  return session.expiresAt - EXPIRY_GRACE_MS <= Date.now();
}

function readStoredSession(): AuthSession | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AuthSession;
    if (
      !parsed?.token ||
      typeof parsed.expiresAt !== "number" ||
      !parsed.user?.role ||
      !parsed.user?.userId
    ) {
      return null;
    }
    if (isExpired(parsed)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function buildSession(token: string, role: UserRole, expiresInSec: number, email: string): AuthSession {
  const claims = decodeJwtPayload(token);
  const userId = typeof claims?.sub === "string" ? claims.sub : "";
  const expFromClaim = typeof claims?.exp === "number" ? claims.exp * 1000 : null;
  const expiresAt = expFromClaim ?? Date.now() + expiresInSec * 1000;
  return {
    token,
    expiresAt,
    user: { userId, email, role },
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSessionState] = useState<AuthSession | null>(() => readStoredSession());

  useEffect(() => {
    if (session) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }, [session]);

  // Auto-clear the session the moment its token expires so guards downstream
  // can redirect to /login with a clear reason.
  useEffect(() => {
    if (!session) return;
    const remaining = session.expiresAt - EXPIRY_GRACE_MS - Date.now();
    if (remaining <= 0) {
      setSessionState(null);
      return;
    }
    const timer = window.setTimeout(() => setSessionState(null), remaining);
    return () => window.clearTimeout(timer);
  }, [session]);

  const signIn = useCallback(
    async (email: string, password: string, signal?: AbortSignal): Promise<AuthSession> => {
      const trimmed = email.trim();
      const response = await loginRequest({ email: trimmed, password }, signal);
      const next = buildSession(response.access_token, response.role, response.expires_in, trimmed);
      setSessionState(next);
      return next;
    },
    [],
  );

  const signOut = useCallback(() => setSessionState(null), []);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      isAuthenticated: session !== null && !isExpired(session),
      signIn,
      signOut,
    }),
    [session, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
