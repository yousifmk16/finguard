import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useRole } from "@/features/auth/useRole";

export default function AdminRoute({ children }: { children: ReactNode }) {
  const { isAdmin } = useRole();
  if (!isAdmin) {
    return <Navigate to="/forbidden?required=admin" replace />;
  }
  return <>{children}</>;
}
