import { Link } from "react-router-dom";
import RoleGate from "@/components/auth/RoleGate";
import { useAuth } from "@/features/auth/useAuth";
import { useRole } from "@/features/auth/useRole";
import { formatDateTime } from "@/lib/formatters";

export default function SettingsPage() {
  const { session } = useAuth();
  const { role, isAdmin } = useRole();

  if (!session) return null;

  const expiresAt = new Date(session.expiresAt).toISOString();

  return (
    <section className="settings-page">
      <header className="settings-page__header">
        <h1>Settings</h1>
        <p className="settings-page__subtitle">
          Personal session details. Role-scoped capabilities are listed below.
        </p>
      </header>

      <div className="settings-grid">
        <article className="card">
          <header className="card__header">
            <h2>Session</h2>
          </header>
          <dl className="settings-list">
            <Field label="Email" value={session.user.email} />
            <Field
              label="Role"
              value={
                <span className={`badge badge--role badge--role-${role ?? "unknown"}`}>
                  {role}
                </span>
              }
            />
            <Field label="User ID" value={<code>{session.user.userId || "—"}</code>} />
            <Field label="Token expires" value={formatDateTime(expiresAt)} />
          </dl>
        </article>

        <article className="card">
          <header className="card__header">
            <h2>Capabilities</h2>
          </header>
          <ul className="capabilities">
            <li>View dashboards, anomalies, and alerts</li>
            <li>Acknowledge, resolve, suppress, and reopen anomalies</li>
            <li className={isAdmin ? "" : "capabilities__locked"}>
              Manage policies
              <RoleGate roles={["admin"]} fallback={<span className="capabilities__tag">Admin</span>}>
                <Link to="/policies" className="capabilities__link">Open</Link>
              </RoleGate>
            </li>
            <li className={isAdmin ? "" : "capabilities__locked"}>
              Manage users
              <RoleGate roles={["admin"]} fallback={<span className="capabilities__tag">Admin</span>}>
                <Link to="/users" className="capabilities__link">Open</Link>
              </RoleGate>
            </li>
          </ul>
          {!isAdmin ? (
            <p className="settings-page__note">
              Need elevated permissions? Contact your workspace administrator.
            </p>
          ) : null}
        </article>
      </div>
    </section>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="field">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
