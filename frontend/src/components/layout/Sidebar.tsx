import { useLocation, useNavigate } from "react-router-dom";
import Icon from "@/components/common/Icon";
import { useRole } from "@/features/auth/useRole";

export default function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { isAdmin } = useRole();
  const path = location.pathname;

  const isActive = (id: string) => {
    if (id === "dashboard") return path === "/" || path === "/dashboard";
    if (id === "anomalies") return path.startsWith("/anomalies");
    if (id === "alerts") return path === "/alerts";
    if (id === "policies") return path === "/policies";
    if (id === "settings") return path === "/settings";
    if (id === "users") return path === "/users";
    if (id === "datagen") return path === "/datagen";
    return false;
  };

  const items = [
    { id: "dashboard", icon: "dashboard", label: "Operations", to: "/dashboard" },
    { id: "anomalies", icon: "alert", label: "Anomalies", to: "/anomalies" },
    { id: "alerts", icon: "bell", label: "Alerts", to: "/alerts" },
    { id: "policies", icon: "policy", label: "Policies", to: "/policies" },
  ];

  const items2 = [
    { id: "settings", icon: "settings", label: "Settings", to: "/settings" },
    ...(isAdmin ? [{ id: "users", icon: "users", label: "Users", to: "/users" }] : []),
    ...(isAdmin ? [{ id: "datagen", icon: "sparkles", label: "Data Gen", to: "/datagen" }] : []),
  ];

  return (
    <nav className="sidebar">
      <div className="side-section">
        <div className="side-section-label">Detection</div>
        {items.map((it) => (
          <button
            key={it.id}
            type="button"
            className={`nav-item ${isActive(it.id) ? "active" : ""}`}
            onClick={() => navigate(it.to)}
          >
            <Icon name={it.icon} size={15} />
            <span className="label">{it.label}</span>
          </button>
        ))}
      </div>
      <div className="side-section">
        <div className="side-section-label">Workspace</div>
        {items2.map((it) => (
          <button
            key={it.id}
            type="button"
            className={`nav-item ${isActive(it.id) ? "active" : ""}`}
            onClick={() => navigate(it.to)}
          >
            <Icon name={it.icon} size={15} />
            <span className="label">{it.label}</span>
          </button>
        ))}
      </div>

      <div className="sidebar-footer">
        <div className="sb-stat">
          <div className="lbl">PIPELINE</div>
          <div className="val" style={{ color: "var(--accent)" }}>● HEALTHY</div>
        </div>
        <div className="sb-stat">
          <div className="lbl">ROLE</div>
          <div className="val" style={{ textTransform: "uppercase" }}>{isAdmin ? "ADMIN" : "ANALYST"}</div>
        </div>
      </div>
    </nav>
  );
}
