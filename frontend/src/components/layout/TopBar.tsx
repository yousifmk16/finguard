import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Icon from "@/components/common/Icon";
import { useAuth } from "@/features/auth/useAuth";
import { useRole } from "@/features/auth/useRole";

interface TopBarProps {
  onToggleSidebar: () => void;
}

export default function TopBar({ onToggleSidebar }: TopBarProps) {
  const { session, signOut } = useAuth();
  const { role } = useRole();
  const navigate = useNavigate();
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const i = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(i);
  }, []);

  const t = new Date(now);
  const pad = (n: number) => String(n).padStart(2, "0");
  const clock = `${pad(t.getUTCHours())}:${pad(t.getUTCMinutes())}:${pad(t.getUTCSeconds())} UTC`;
  const date = `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}`;

  const initials = session?.user?.email
    ? session.user.email.slice(0, 2).toUpperCase()
    : "??";

  const handleLogout = () => {
    signOut();
    navigate("/login", { replace: true });
  };

  return (
    <div className="topbar">
      <div className="brand">
        <span className="brand-mark" />
        <span className="brand-text">FINGUARD</span>
      </div>
      <div className="topbar-center">
        <button className="tb-btn" onClick={onToggleSidebar} type="button">
          <Icon name="menu" size={14} />
        </button>
        <button className="tb-btn" type="button">
          <Icon name="search" size={14} /> Search <span className="kbd">Ctrl+K</span>
        </button>
        <span className="tb-divider" />
        <span className="live-pill">
          <span className="live-dot" />
          LIVE
        </span>
        <span className="tb-divider" />
        <span className="clock">
          <span style={{ color: "var(--text-dim)" }}>{date}</span> {clock}
        </span>
      </div>
      <div className="topbar-right">
        {role === "analyst" && (
          <span
            className="badge-soft"
            style={{
              borderColor: "var(--sev-med)",
              color: "var(--sev-med)",
              letterSpacing: "0.08em",
            }}
          >
            <Icon name="shield" size={11} /> READ-ONLY
          </span>
        )}
        <button className="tb-btn" type="button" onClick={() => navigate("/alerts")}>
          <Icon name="bell" size={14} />
        </button>
        <button className="tb-btn" type="button">
          <Icon name="logs" size={14} />
        </button>
        <span className="tb-divider" />
        <button className="user-chip" type="button" onClick={handleLogout} title="Sign out">
          <span className="avatar">{initials}</span>
          <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", lineHeight: 1.1 }}>
            <span style={{ fontSize: 12 }}>{session?.user?.email ?? "user"}</span>
            <span className="role">{role}</span>
          </span>
        </button>
      </div>
    </div>
  );
}
