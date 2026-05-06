import { useAuth } from "./useAuth";
import type { UserRole } from "./AuthContext";

export interface RoleInfo {
  role: UserRole | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  isAnalyst: boolean;
  /** True iff the user's role appears in ``allowed``. */
  hasAnyRole: (allowed: readonly UserRole[]) => boolean;
}

/**
 * UI-09: Single source of truth for role checks across the UI.
 *
 * Mirrors the backend's RBAC dependencies (``require_admin`` /
 * ``require_analyst_or_admin``). When a new role lands on the backend,
 * widening this hook is the only change the rest of the UI needs.
 */
export function useRole(): RoleInfo {
  const { session, isAuthenticated } = useAuth();
  const role = session?.user.role ?? null;

  return {
    role,
    isAuthenticated,
    isAdmin: role === "admin",
    isAnalyst: role === "analyst",
    hasAnyRole: (allowed) => (role !== null ? allowed.includes(role) : false),
  };
}
