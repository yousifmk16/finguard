import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import Icon from "@/components/common/Icon";
import { ApiError, apiFetch } from "@/lib/api";
import { useAuth } from "./useAuth";

const REASON_MESSAGES: Record<string, string> = {
  expired: "Your session expired. Please sign in again.",
  required: "Please sign in to continue.",
};

export default function LoginPage() {
  const { signIn, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();

  const fromPath = (location.state as { from?: string } | null)?.from ?? "/dashboard";
  const reasonKey = searchParams.get("reason");
  const reasonMessage = reasonKey ? REASON_MESSAGES[reasonKey] ?? null : null;

  const [mode, setMode] = useState<"signin" | "signup">("signin");

  // sign-in state
  const [email, setEmail] = useState("yousif.k@acme.io");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // sign-up state
  const [suEmail, setSuEmail] = useState("");
  const [suPassword, setSuPassword] = useState("");
  const [suConfirm, setSuConfirm] = useState("");
  const [suSubmitting, setSuSubmitting] = useState(false);
  const [suError, setSuError] = useState<string | null>(null);

  useEffect(() => {
    if (isAuthenticated) navigate(fromPath, { replace: true });
  }, [isAuthenticated, fromPath, navigate]);

  const switchMode = (next: "signin" | "signup") => {
    setMode(next);
    setErrorMessage(null);
    setSuError(null);
  };

  /* ── Sign in ── */
  const handleSignIn = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (submitting) return;
    setErrorMessage(null);
    const trimmedEmail = email.trim();
    if (!trimmedEmail || !password) {
      setErrorMessage("Email and password are required.");
      return;
    }
    setSubmitting(true);
    try {
      await signIn(trimmedEmail, password);
      navigate(fromPath, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) setErrorMessage("Invalid email or password.");
        else if (err.status === 503) setErrorMessage("Authentication service unavailable. Try again shortly.");
        else if (err.status === 0) setErrorMessage("Could not reach the server. Check your connection.");
        else setErrorMessage(err.detail || "Sign in failed. Please try again.");
      } else {
        setErrorMessage("Sign in failed. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  /* ── Sign up ── */
  const handleSignUp = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (suSubmitting) return;
    setSuError(null);
    const trimmed = suEmail.trim();
    if (!trimmed || !suPassword) { setSuError("Email and password are required."); return; }
    if (suPassword.length < 8) { setSuError("Password must be at least 8 characters."); return; }
    if (suPassword !== suConfirm) { setSuError("Passwords do not match."); return; }
    setSuSubmitting(true);
    try {
      const res = await apiFetch<{ access_token: string; role: string; expires_in: number }>(
        "/auth/register",
        { method: "POST", body: { email: trimmed, password: suPassword } },
      );
      // sign in with the returned token via the normal signIn flow so AuthContext
      // is fully populated
      await signIn(trimmed, suPassword);
      navigate(fromPath, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409) setSuError("An account with that email already exists.");
        else if (err.status === 422) setSuError(err.detail || "Validation error.");
        else if (err.status === 0) setSuError("Could not reach the server.");
        else setSuError(err.detail || "Registration failed. Please try again.");
      } else {
        setSuError("Registration failed. Please try again.");
      }
    } finally {
      setSuSubmitting(false);
    }
  };

  const inputStyle = "input";

  return (
    <div className="login-shell">
      {/* Left art panel */}
      <div className="login-art">
        <div className="grid-bg" />
        <div style={{ position: "relative", zIndex: 1, display: "flex", alignItems: "center", gap: 10 }}>
          <span className="brand-mark" />
          <span style={{ fontFamily: "var(--mono)", fontSize: 13, letterSpacing: "0.08em", fontWeight: 600 }}>
            FINGUARD
          </span>
        </div>

        <div style={{ position: "relative", zIndex: 1, maxWidth: 480 }}>
          <div style={{ fontFamily: "var(--mono)", fontSize: 10.5, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--text-dim)", marginBottom: 10 }}>
            v1.4
          </div>
          <div style={{ fontSize: 32, fontWeight: 600, lineHeight: 1.15, letterSpacing: "-0.02em" }}>
            Real-time anomaly detection for cloud spend.
          </div>
          <div style={{ color: "var(--text-mute)", marginTop: 14, fontSize: 13.5, lineHeight: 1.6, maxWidth: 420 }}>
            Hybrid detection across time-series, isolation forest, and rules — with explainable alerts you can triage in seconds.
          </div>
          <div style={{ display: "flex", gap: 24, marginTop: 24, fontSize: 12, color: "var(--text-mute)", fontFamily: "var(--mono)" }}>
            <div><span style={{ color: "var(--accent)" }}>●</span> 3 providers</div>
            <div><span style={{ color: "var(--accent)" }}>●</span> 47 rules active</div>
          </div>
        </div>

        <div className="stream">
          <div className="line">[14:23:11] ingest <span style={{ color: "var(--accent)" }}>accepted</span> evt 3fa85f64-… bigquery/us-central1</div>
          <div className="line">[14:23:09] feature_eng vector built acct gcp-project-42 z=2.18</div>
          <div className="line hi">[14:23:08] anomaly <span style={{ color: "var(--text)" }}>HIGH</span> bigquery/us-central1 score=0.91 +318%</div>
          <div className="line">[14:23:07] alert dispatched email + slack dedup_key gcp-project-42::BigQuery</div>
          <div className="line md">[14:23:05] iso_forest model_drift retrain queued</div>
          <div className="line ok">[14:23:00] heartbeat fusion ok rule_engine ok alert_orchestrator ok</div>
        </div>
      </div>

      {/* Right form panel */}
      <div className="login-form-wrap">
        <div className="login-form">

          {/* Mode toggle */}
          <div className="login-form__tabs">
            <button
              type="button"
              className={`login-form__tab${mode === "signin" ? " active" : ""}`}
              onClick={() => switchMode("signin")}
            >
              Log in
            </button>
            <button
              type="button"
              className={`login-form__tab${mode === "signup" ? " active" : ""}`}
              onClick={() => switchMode("signup")}
            >
              Sign up
            </button>
          </div>

          {/* ── Sign in form ── */}
          {mode === "signin" && (
            <form onSubmit={handleSignIn} noValidate>
              <div className="sub" style={{ marginBottom: 20 }}>Continue to your operations console.</div>

              {reasonMessage && !errorMessage && (
                <p className="login-form__notice" role="status">{reasonMessage}</p>
              )}
              {errorMessage && (
                <p className="login-form__error" role="alert">{errorMessage}</p>
              )}

              <div className="field">
                <label htmlFor="login-email">email</label>
                <input id="login-email" className={inputStyle} value={email} onChange={(e) => setEmail(e.target.value)} type="email" autoComplete="username" disabled={submitting} />
              </div>
              <div className="field">
                <label htmlFor="login-password">password</label>
                <input id="login-password" className={inputStyle} value={password} onChange={(e) => setPassword(e.target.value)} type="password" autoComplete="current-password" disabled={submitting} />
              </div>

              <button className="btn primary full" type="submit" disabled={submitting || !email.trim() || !password}>
                {submitting ? "Signing in\u2026" : <>Sign in <Icon name="chevron-right" size={13} /></>}
              </button>

              <div style={{ marginTop: 24, fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--text-dim)", letterSpacing: "0.06em" }}>
                FINGUARD · status: <span style={{ color: "var(--accent)" }}>● operational</span>
              </div>
            </form>
          )}

          {/* ── Sign up form ── */}
          {mode === "signup" && (
            <form onSubmit={handleSignUp} noValidate>
              <div className="sub" style={{ marginBottom: 20 }}>Create your admin account.</div>

              {suError && (
                <p className="login-form__error" role="alert">{suError}</p>
              )}

              <div className="field">
                <label htmlFor="su-email">email</label>
                <input id="su-email" className={inputStyle} value={suEmail} onChange={(e) => setSuEmail(e.target.value)} type="email" autoComplete="username" disabled={suSubmitting} />
              </div>
              <div className="field">
                <label htmlFor="su-password">password</label>
                <input id="su-password" className={inputStyle} value={suPassword} onChange={(e) => setSuPassword(e.target.value)} type="password" autoComplete="new-password" disabled={suSubmitting} />
              </div>
              <div className="field">
                <label htmlFor="su-confirm">confirm password</label>
                <input id="su-confirm" className={inputStyle} value={suConfirm} onChange={(e) => setSuConfirm(e.target.value)} type="password" autoComplete="new-password" disabled={suSubmitting} />
              </div>

              <button
                className="btn primary full"
                type="submit"
                disabled={suSubmitting || !suEmail.trim() || !suPassword || !suConfirm}
              >
                {suSubmitting ? "Creating account\u2026" : <>Create account <Icon name="chevron-right" size={13} /></>}
              </button>

              <div style={{ marginTop: 16, fontSize: 11.5, color: "var(--text-dim)", textAlign: "center" }}>
                New accounts are granted <span style={{ color: "var(--accent)" }}>admin</span> role by default.
              </div>
            </form>
          )}

        </div>
      </div>
    </div>
  );
}
