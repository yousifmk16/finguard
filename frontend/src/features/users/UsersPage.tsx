import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/features/auth/useAuth";
import { useRole } from "@/features/auth/useRole";
import { formatDateTime } from "@/lib/formatters";
import Icon from "@/components/common/Icon";

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
  const { isAdmin } = useRole();
  const [data, setData] = useState<UsersResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [updatingRoleId, setUpdatingRoleId] = useState<string | null>(null);

  const handleDelete = async (userId: string) => {
    if (!session || !window.confirm("Delete this user? This cannot be undone.")) return;
    setDeletingId(userId);
    try {
      await apiFetch(`/users/${userId}`, { method: "DELETE", token: session.token });
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to delete user");
    } finally {
      setDeletingId(null);
    }
  };

  const handleRoleChange = async (userId: string, newRole: string) => {
    if (!session) return;
    setUpdatingRoleId(userId);
    try {
      await apiFetch(`/users/${userId}/role`, { method: "PATCH", token: session.token, body: { role: newRole } });
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to update role");
    } finally {
      setUpdatingRoleId(null);
    }
  };

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

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="page fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">Users</h1>
          <div className="page-sub">
            <span className="mono">{total}</span> members with access
          </div>
        </div>
        <div className="page-actions">
          <button className="btn" type="button" onClick={load} disabled={loading}>
            {loading ? "Refreshing\u2026" : "Refresh"}
          </button>
          {isAdmin && (
            <button className="btn" type="button" onClick={() => setShowForm((v) => !v)}>
              {showForm ? "Cancel" : "+ Add user"}
            </button>
          )}
        </div>
      </div>

      {showForm && (
        <AddUserForm
          token={session?.token ?? null}
          onCreated={() => { setShowForm(false); load(); }}
          onCancel={() => setShowForm(false)}
        />
      )}

      {error && (
        <div style={{ padding: "10px 14px", background: "var(--sev-high-bg)", border: "1px solid var(--sev-high)", borderRadius: "var(--r-md)", marginBottom: 14, fontSize: 12.5, color: "var(--sev-high)" }}>
          {error}
        </div>
      )}

      <div className="table-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>EMAIL</th>
              <th style={{ width: 90 }}>ROLE</th>
              <th style={{ width: 90 }}>STATUS</th>
              <th>CREATED</th>
              {isAdmin && <th style={{ width: 48 }} />}
            </tr>
          </thead>
          <tbody>
            {loading && items.length === 0 ? (
              <tr><td colSpan={isAdmin ? 5 : 4} style={{ textAlign: "center", padding: 40, color: "var(--text-mute)" }}>Loading users...</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={isAdmin ? 5 : 4}><div className="empty"><div className="big">NO USERS</div></div></td></tr>
            ) : items.map((u) => (
              <tr key={u.user_id}>
                <td style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <div style={{ width: 26, height: 26, borderRadius: "50%", background: "var(--surface-3)", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 9.5, color: "var(--text-mute)", fontWeight: 600, flexShrink: 0 }}>
                    {u.email.slice(0, 2).toUpperCase()}
                  </div>
                  {u.email}
                </td>
                <td>
                  {isAdmin && u.user_id !== session?.user.userId ? (
                    <select
                      className="mono"
                      value={u.role}
                      disabled={updatingRoleId === u.user_id}
                      onChange={(e) => handleRoleChange(u.user_id, e.target.value)}
                      style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: "0.04em", color: u.role === "admin" ? "var(--accent)" : "var(--text-mute)", background: "transparent", border: "1px solid var(--border)", borderRadius: "var(--r-sm)", padding: "2px 4px", cursor: "pointer", opacity: updatingRoleId === u.user_id ? 0.5 : 1 }}
                    >
                      <option value="analyst">analyst</option>
                      <option value="admin">admin</option>
                    </select>
                  ) : (
                    <span className="mono" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: "0.04em", color: u.role === "admin" ? "var(--accent)" : "var(--text-mute)" }}>
                      {u.role}
                    </span>
                  )}
                </td>
                <td>
                  <span className="mono" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: "0.04em", color: u.is_active ? "var(--accent)" : "var(--text-dim)" }}>
                    ● {u.is_active ? "active" : "inactive"}
                  </span>
                </td>
                <td className="mono" style={{ color: "var(--text-mute)" }}>{formatDateTime(u.created_at)}</td>
                {isAdmin && (
                  <td style={{ textAlign: "center" }}>
                    <button
                      type="button"
                      className="btn ghost sm"
                      title="Delete user"
                      disabled={deletingId === u.user_id}
                      onClick={() => handleDelete(u.user_id)}
                      style={{ padding: "3px 7px", color: "var(--sev-high)", opacity: deletingId === u.user_id ? 0.5 : 1 }}
                    >
                      <Icon name="trash" size={13} />
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

    </div>
  );
}

function AddUserForm({ token, onCreated, onCancel }: {
  token: string | null;
  onCreated: () => void;
  onCancel: () => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"analyst" | "admin">("analyst");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) return;
    if (password.length < 8) { setError("Password must be at least 8 characters."); return; }
    setSubmitting(true);
    setError(null);
    try {
      await apiFetch("/users", { method: "POST", token, body: { email: email.trim(), password, role } });
      onCreated();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create user");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} style={{ background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: "var(--r-md)", padding: 16, marginBottom: 14, display: "grid", gridTemplateColumns: "1fr 1fr auto auto", gap: 10, alignItems: "end" }}>
      <div>
        <label style={{ display: "block", fontSize: 11, color: "var(--text-mute)", fontFamily: "var(--mono)", marginBottom: 4 }}>EMAIL</label>
        <input className="input" type="email" placeholder="user@example.com" value={email} onChange={(e) => setEmail(e.target.value)} disabled={submitting} required style={{ width: "100%" }} />
      </div>
      <div>
        <label style={{ display: "block", fontSize: 11, color: "var(--text-mute)", fontFamily: "var(--mono)", marginBottom: 4 }}>PASSWORD</label>
        <input className="input" type="password" placeholder="min 8 characters" value={password} onChange={(e) => setPassword(e.target.value)} disabled={submitting} required style={{ width: "100%" }} />
      </div>
      <div>
        <label style={{ display: "block", fontSize: 11, color: "var(--text-mute)", fontFamily: "var(--mono)", marginBottom: 4 }}>ROLE</label>
        <select className="input" value={role} onChange={(e) => setRole(e.target.value as "analyst" | "admin")} disabled={submitting} style={{ width: "100%" }}>
          <option value="analyst">analyst</option>
          <option value="admin">admin</option>
        </select>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn ghost sm" type="button" onClick={onCancel} disabled={submitting}>Cancel</button>
        <button className="btn sm" type="submit" disabled={submitting || !email.trim() || !password}>
          {submitting ? "Creating…" : "Create"}
        </button>
      </div>
      {error && <div style={{ gridColumn: "1 / -1", fontSize: 12, color: "var(--sev-high)" }}>{error}</div>}
    </form>
  );
}
