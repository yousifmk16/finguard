import type { ReactNode } from "react";
import { useRole } from "@/features/auth/useRole";
import type { UserRole } from "@/features/auth/AuthContext";

interface RoleGateProps {
  /** Roles permitted to see ``children``. Empty array hides for everyone. */
  roles: readonly UserRole[];
  children: ReactNode;
  /** Optional content shown to users whose role is not in ``roles``. */
  fallback?: ReactNode;
}

/**
 * UI-09: Inline role gate.
 *
 * Use for small in-page sections (callouts, action buttons, sidebar items).
 * For full pages, prefer ``<AdminRoute>`` so the user is redirected to
 * ``/forbidden`` rather than silently shown nothing.
 */
export default function RoleGate({ roles, children, fallback = null }: RoleGateProps) {
  const { hasAnyRole } = useRole();
  return <>{hasAnyRole(roles) ? children : fallback}</>;
}
