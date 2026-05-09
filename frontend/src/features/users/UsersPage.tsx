import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/features/auth/useAuth";
import { formatDateTime } from "@/lib/formatters";

interface UserRecord {
  user_id: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

interface UsersResponse {
  items: UserRecord[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export default function UsersPage() {
  const { session } = useAuth();
  const [data, setData] = useState<UsersResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    apiFetch<UsersResponse>("/users", { token: session.token })
      .then(setData)
      .catch((e) => setError(e.detail ?? "Failed to load users"))
      .finally(() => setLoading(false));
  };

  useEffect(load, [session]);

  return (
    <section className="fade-in">
      <header className="page-head">
        <div>
          <h1>Users</h1>
          <p className="sub">Admin accounts with access to FinGuard.</p>
        </div>
        <button type="button" className="btn btn--primary btn--sm btn--pill" onClick={load} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </header>

      {error ? (
        <div className="state-banner state-banner--error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={load}>Try again</button>
        </div>
      ) : null}

      <div className="data-table__wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {loading && !data ? (
              <tr>
                <td colSpan={4} className="data-table__placeholder">Loading…</td>
              </tr>
            ) : data?.items.length === 0 ? (
              <tr>
                <td colSpan={4} className="data-table__placeholder">No users found.</td>
              </tr>
            ) : (
              data?.items.map((u) => (
                <tr key={u.user_id}>
                  <td style={{ fontWeight: 500 }}>{u.email}</td>
                  <td>
                    <span className={`badge badge--role`} style={
                      u.role === "admin"
                        ? { background: "var(--c-med-bg)", color: "var(--c-med)", borderColor: "var(--c-med-border)" }
                        : {}
                    }>
                      {u.role}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${u.is_active ? "badge--status-resolved" : "badge--status-suppressed"}`}>
                      {u.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td style={{ color: "var(--text-muted)" }}>{formatDateTime(u.created_at)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {data && data.total > 0 ? (
          <div className="pagination">
            <span>{data.total} user{data.total !== 1 ? "s" : ""}</span>
          </div>
        ) : null}
      </div>

      <aside className="admin-callout" role="note" style={{ marginTop: 16 }}>
        <span className="admin-callout__badge">Info</span>
        <span>To add new users, run <code style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>python scripts/create_user.py</code> from the <code style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>backend/</code> folder.</span>
      </aside>
    </section>
  );
}
