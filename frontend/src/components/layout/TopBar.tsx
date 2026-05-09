import { useLocation, useNavigate, Link } from "react-router-dom";
import { useAlertCount } from "@/features/alerts/useAlertCount";

export default function TopBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { pending } = useAlertCount();

  const crumbs = buildCrumbs(location.pathname);

  return (
    <header className="app-topbar">
      {/* Breadcrumbs */}
      <nav className="app-topbar__crumbs" aria-label="Breadcrumb">
        {crumbs.map((c, i) => (
          <span key={i} style={{ display: "contents" }}>
            {i > 0 ? <span className="sep">/</span> : null}
            {i === crumbs.length - 1 ? (
              <strong>{c.label}</strong>
            ) : c.to ? (
              <Link to={c.to}>{c.label}</Link>
            ) : (
              <span>{c.label}</span>
            )}
          </span>
        ))}
      </nav>

      {/* Actions */}
      <div className="app-topbar__actions">
        {/* Search */}
        <label className="app-topbar__search" aria-label="Search">
          <SearchIcon />
          <input
            type="search"
            placeholder="Search anomalies, accounts, services…"
            onKeyDown={(e) => {
              if (e.key === "Enter" && e.currentTarget.value) {
                navigate(`/anomalies?service=${encodeURIComponent(e.currentTarget.value)}`);
                e.currentTarget.value = "";
              }
            }}
          />
          <kbd aria-hidden="true">⌘K</kbd>
        </label>

        {/* Alerts bell */}
        <button
          type="button"
          className="app-topbar__icon-btn"
          onClick={() => navigate("/alerts")}
          aria-label={`Alerts${pending > 0 ? `, ${pending} pending` : ""}`}
          title="Alert Center"
        >
          <BellIcon />
          {pending > 0 ? <span className="app-topbar__bell-dot" aria-hidden="true" /> : null}
        </button>
      </div>
    </header>
  );
}

/* ---- Breadcrumb builder ---------------------------------------- */
interface Crumb { label: string; to?: string; }

function buildCrumbs(pathname: string): Crumb[] {
  const segments = pathname.split("/").filter(Boolean);
  const crumbs: Crumb[] = [{ label: "FinGuard" }];

  if (segments.length === 0) return crumbs;

  const labels: Record<string, string> = {
    dashboard: "Dashboard",
    anomalies: "Anomalies",
    alerts:    "Alerts",
    policies:  "Policies",
    users:     "Users",
    settings:  "Settings",
  };

  segments.forEach((seg, i) => {
    const isLast = i === segments.length - 1;
    const label = labels[seg] ?? seg;
    const to = "/" + segments.slice(0, i + 1).join("/");
    crumbs.push({ label, to: isLast ? undefined : to });
  });

  return crumbs;
}

/* ---- Icons ----------------------------------------------------- */
function SearchIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5l3 3" strokeLinecap="round" />
    </svg>
  );
}
function BellIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M8 2a4 4 0 0 1 4 4v3l1 2H3l1-2V6a4 4 0 0 1 4-4Z" />
      <path d="M6.5 13a1.5 1.5 0 0 0 3 0" />
    </svg>
  );
}
