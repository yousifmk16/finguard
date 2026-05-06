import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "@/features/auth/useAuth";

export default function AdminRoute({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  if (session?.user.role !== "admin") {
    return <Navigate to="/forbidden" replace />;
  }
  return <>{children}</>;
}
