import { useNavigate } from "react-router-dom";
import { useAuth } from "@/features/auth/useAuth";
import { useRole } from "@/features/auth/useRole";

export default function TopBar() {
  const { session, signOut } = useAuth();
  const { role, isAdmin } = useRole();
  const navigate = useNavigate();

  const handleSignOut = () => {
    signOut();
    navigate("/login", { replace: true });
  };

  return (
    <header className="app-topbar">
      <div className="app-topbar__title">Real-Time Cloud Billing Anomaly Detection</div>
      <div className="app-topbar__user">
        {session ? (
          <>
            <span
              className={`app-topbar__role app-topbar__role--${role ?? "unknown"}`}
              title={isAdmin ? "Full administrative access" : "Read + lifecycle access"}
            >
              {role}
            </span>
            <span className="app-topbar__email">{session.user.email}</span>
            <button type="button" className="app-topbar__signout" onClick={handleSignOut}>
              Sign out
            </button>
          </>
        ) : null}
      </div>
    </header>
  );
}
