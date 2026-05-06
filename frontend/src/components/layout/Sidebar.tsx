import { NavLink } from "react-router-dom";
import { useRole } from "@/features/auth/useRole";
import { useAlertCount } from "@/features/alerts/useAlertCount";
import type { UserRole } from "@/features/auth/AuthContext";

interface NavItem {
  to: string;
  label: string;
  /** Roles permitted to see this item. Omit to show to every signed-in user. */
  roles?: readonly UserRole[];
}

const NAV_ITEMS: NavItem[] = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/anomalies", label: "Anomalies" },
  { to: "/alerts", label: "Alerts" },
  { to: "/policies", label: "Policies", roles: ["admin"] },
  { to: "/users", label: "Users", roles: ["admin"] },
  { to: "/settings", label: "Settings" },
];

export default function Sidebar() {
  const { hasAnyRole } = useRole();
  const { pending, stale } = useAlertCount();

  const visibleItems = NAV_ITEMS.filter(
    (item) => !item.roles || hasAnyRole(item.roles),
  );

  return (
    <aside className="app-sidebar" aria-label="Primary navigation">
      <div className="app-sidebar__brand">FinGuard</div>
      <nav className="app-sidebar__nav">
        <ul>
          {visibleItems.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                className={({ isActive }) =>
                  `app-sidebar__link${isActive ? " app-sidebar__link--active" : ""}`
                }
              >
                <span>{item.label}</span>
                {item.to === "/alerts" && pending > 0 ? (
                  <span
                    className={`app-sidebar__count${stale ? " app-sidebar__count--stale" : ""}`}
                    aria-label={`${pending} pending alert${pending === 1 ? "" : "s"}${stale ? " (last update failed)" : ""}`}
                  >
                    {pending > 99 ? "99+" : pending}
                  </span>
                ) : null}
                {item.roles?.includes("admin") ? (
                  <span className="app-sidebar__badge">Admin</span>
                ) : null}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
