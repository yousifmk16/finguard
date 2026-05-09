import { NavLink, useNavigate } from "react-router-dom";
import { useRole } from "@/features/auth/useRole";
import { useAuth } from "@/features/auth/useAuth";
import { useAlertCount } from "@/features/alerts/useAlertCount";

export default function Sidebar() {
  const { session, signOut } = useAuth();
  const { role, hasAnyRole } = useRole();
  const { pending, stale } = useAlertCount();
  const navigate = useNavigate();

  const handleSignOut = () => {
    signOut();
    navigate("/login", { replace: true });
  };

  const initials = session?.user?.email
    ? session.user.email.slice(0, 2).toUpperCase()
    : "??";

  return (
    <aside className="app-sidebar" aria-label="Primary navigation">
      {/* Brand */}
      <div className="app-sidebar__brand">
        <span className="app-sidebar__brand-mark" aria-hidden="true">F</span>
        <span>FinGuard</span>
      </div>

      <nav className="app-sidebar__nav">
        {/* Monitoring */}
        <div className="app-sidebar__section">Monitoring</div>
        <ul>
          <li>
            <NavLink
              to="/dashboard"
              className={({ isActive }) =>
                `app-sidebar__link${isActive ? " app-sidebar__link--active" : ""}`
              }
            >
              <IconDashboard className="app-sidebar__icon" />
              Dashboard
            </NavLink>
          </li>
          <li>
            <NavLink
              to="/anomalies"
              className={({ isActive }) =>
                `app-sidebar__link${isActive ? " app-sidebar__link--active" : ""}`
              }
            >
              <IconAnomalies className="app-sidebar__icon" />
              Anomalies
            </NavLink>
          </li>
          <li>
            <NavLink
              to="/alerts"
              className={({ isActive }) =>
                `app-sidebar__link${isActive ? " app-sidebar__link--active" : ""}`
              }
            >
              <IconBell className="app-sidebar__icon" />
              <span>Alerts</span>
              {pending > 0 ? (
                <span
                  className={`app-sidebar__count${stale ? " app-sidebar__count--stale" : ""}`}
                  aria-label={`${pending} pending alert${pending === 1 ? "" : "s"}${stale ? " (stale)" : ""}`}
                >
                  {pending > 99 ? "99+" : pending}
                </span>
              ) : null}
            </NavLink>
          </li>
        </ul>

        {/* Configure (admin only) */}
        {hasAnyRole(["admin"]) ? (
          <>
            <div className="app-sidebar__section">Configure</div>
            <ul>
              <li>
                <NavLink
                  to="/policies"
                  className={({ isActive }) =>
                    `app-sidebar__link${isActive ? " app-sidebar__link--active" : ""}`
                  }
                >
                  <IconShield className="app-sidebar__icon" />
                  <span>Policies</span>
                  <span className="app-sidebar__badge">Admin</span>
                </NavLink>
              </li>
              <li>
                <NavLink
                  to="/users"
                  className={({ isActive }) =>
                    `app-sidebar__link${isActive ? " app-sidebar__link--active" : ""}`
                  }
                >
                  <IconUsers className="app-sidebar__icon" />
                  <span>Users</span>
                  <span className="app-sidebar__badge">Admin</span>
                </NavLink>
              </li>
            </ul>
          </>
        ) : null}

        {/* Workspace */}
        <div className="app-sidebar__section">Workspace</div>
        <ul>
          <li>
            <NavLink
              to="/settings"
              className={({ isActive }) =>
                `app-sidebar__link${isActive ? " app-sidebar__link--active" : ""}`
              }
            >
              <IconSettings className="app-sidebar__icon" />
              Settings
            </NavLink>
          </li>
        </ul>
      </nav>

      {/* Footer */}
      {session ? (
        <div className="app-sidebar__foot">
          <div className="avatar" aria-hidden="true">{initials}</div>
          <div style={{ flex: 1, minWidth: 0, overflow: "hidden" }}>
            <div style={{ fontWeight: 600, fontSize: 12.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {session.user.email}
            </div>
            <div style={{ fontSize: 11, color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              {role}
            </div>
          </div>
          <button
            type="button"
            onClick={handleSignOut}
            title="Sign out"
            style={{
              width: 28, height: 28,
              display: "grid", placeItems: "center",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border)",
              background: "transparent",
              color: "var(--text-muted)",
              flexShrink: 0,
            }}
          >
            <IconSignOut />
          </button>
        </div>
      ) : null}
    </aside>
  );
}

/* ---- Inline SVG icons ------------------------------------------ */
function IconDashboard({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="1" y="1" width="6" height="6" rx="1" />
      <rect x="9" y="1" width="6" height="6" rx="1" />
      <rect x="1" y="9" width="6" height="6" rx="1" />
      <rect x="9" y="9" width="6" height="6" rx="1" />
    </svg>
  );
}
function IconAnomalies({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M8 2L14 13H2L8 2Z" strokeLinejoin="round" />
      <path d="M8 6v3M8 11v.5" strokeLinecap="round" />
    </svg>
  );
}
function IconBell({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M8 2a4 4 0 0 1 4 4v3l1 2H3l1-2V6a4 4 0 0 1 4-4Z" />
      <path d="M6.5 13a1.5 1.5 0 0 0 3 0" />
    </svg>
  );
}
function IconShield({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M8 2L14 5v4c0 3-2.5 5-6 5S2 12 2 9V5L8 2Z" />
      <path d="M5.5 8l1.5 1.5 3-3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function IconUsers({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="6" cy="5" r="2.5" />
      <path d="M1 14c0-3 2-4.5 5-4.5s5 1.5 5 4.5" />
      <circle cx="11.5" cy="5" r="1.5" />
      <path d="M11.5 10c1.5 0 3 .8 3 3" />
    </svg>
  );
}
function IconSettings({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="8" cy="8" r="2" />
      <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.2 3.2l1.4 1.4M11.4 11.4l1.4 1.4M3.2 12.8l1.4-1.4M11.4 4.6l1.4-1.4" strokeLinecap="round" />
    </svg>
  );
}
function IconSignOut() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M10 8H3M7 5l-3 3 3 3" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6 3H13V13H6" strokeLinecap="round" />
    </svg>
  );
}
