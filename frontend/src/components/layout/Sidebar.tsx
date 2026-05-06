import { NavLink } from "react-router-dom";
import { useAuth } from "@/features/auth/useAuth";

interface NavItem {
  to: string;
  label: string;
  adminOnly?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/anomalies", label: "Anomalies" },
  { to: "/alerts", label: "Alerts" },
  { to: "/policies", label: "Policies", adminOnly: true },
  { to: "/users", label: "Users", adminOnly: true },
  { to: "/settings", label: "Settings" },
];

export default function Sidebar() {
  const { session } = useAuth();
  const isAdmin = session?.user.role === "admin";

  const visibleItems = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin);

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
                {item.label}
                {item.adminOnly ? <span className="app-sidebar__badge">Admin</span> : null}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
