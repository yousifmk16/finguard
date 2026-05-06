import { Link, useSearchParams } from "react-router-dom";
import { useRole } from "@/features/auth/useRole";

export default function ForbiddenPage() {
  const [params] = useSearchParams();
  const required = params.get("required");
  const { role, isAuthenticated } = useRole();

  return (
    <div className="error-page">
      <h1>403 — Forbidden</h1>
      {required ? (
        <p>
          This area requires the <strong>{required}</strong> role.
          {isAuthenticated && role
            ? ` You are signed in as ${role}.`
            : null}
        </p>
      ) : (
        <p>You do not have permission to access this area.</p>
      )}

      {isAuthenticated && required && role !== required ? (
        <p className="error-page__hint">
          Contact your workspace administrator if you believe you should have
          access.
        </p>
      ) : null}

      <div className="error-page__actions">
        <Link to="/dashboard">Return to dashboard</Link>
      </div>
    </div>
  );
}
