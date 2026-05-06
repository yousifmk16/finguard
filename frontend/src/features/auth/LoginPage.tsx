import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "@/lib/api";
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

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (isAuthenticated) {
      navigate(fromPath, { replace: true });
    }
  }, [isAuthenticated, fromPath, navigate]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
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
        if (err.status === 401) {
          setErrorMessage("Invalid email or password.");
        } else if (err.status === 503) {
          setErrorMessage("Authentication service is unavailable. Try again shortly.");
        } else if (err.status === 0) {
          setErrorMessage("Could not reach the server. Check your connection.");
        } else {
          setErrorMessage(err.detail || "Sign in failed. Please try again.");
        }
      } else {
        setErrorMessage("Sign in failed. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-shell">
      <form className="login-card" onSubmit={handleSubmit} noValidate>
        <h1 className="login-card__brand">FinGuard</h1>
        <p className="login-card__tagline">Real-Time Cloud Billing Anomaly Detection</p>

        {reasonMessage && !errorMessage ? (
          <p className="login-card__notice" role="status">
            {reasonMessage}
          </p>
        ) : null}

        <label className="login-card__field" htmlFor="login-email">
          <span>Email</span>
          <input
            id="login-email"
            type="email"
            name="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={submitting}
          />
        </label>

        <label className="login-card__field" htmlFor="login-password">
          <span>Password</span>
          <input
            id="login-password"
            type="password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={submitting}
          />
        </label>

        {errorMessage ? (
          <p className="login-card__error" role="alert">
            {errorMessage}
          </p>
        ) : null}

        <button
          type="submit"
          className="login-card__submit"
          disabled={submitting || email.length === 0 || password.length === 0}
        >
          {submitting ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}
