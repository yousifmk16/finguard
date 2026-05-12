import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/features/auth/useAuth";
import { useRole } from "@/features/auth/useRole";
import { apiFetch } from "@/lib/api";
import { formatDateTime, formatRelTime } from "@/lib/formatters";
import { useAuditLog } from "./useAuditLog";
import type { AuditLogEntry } from "./types";
import {
  fetchConnections,
  saveAWS,
  saveGCP,
  removeConnection,
} from "./cloud-api";
import type { ConnectionStatus } from "./cloud-api";
import { listProfiles, activateProfile } from "@/features/training/training-api";
import type { FinGuardProfile } from "@/features/training/training-api";

export default function SettingsPage() {
  const { session } = useAuth();
  const { role, isAdmin } = useRole();

  if (!session) return null;

  const expiresAt = new Date(session.expiresAt).toISOString();

  return (
    <div className="page fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">Settings</h1>
          <div className="page-sub">Workspace configuration and session info.</div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
        {/* Notification channels */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Notification channels</div>
          </div>
          <div className="card-body">
            <ChannelRow label="In-app notifications" sub="Bell icon alerts" defaultOn />
            <ChannelRow label="Email alerts" sub="Sent to team inbox" defaultOn />
            <ChannelRow label="Slack webhook" sub="Not configured" defaultOn={false} configured={false} />
            <ChannelRow label="PagerDuty" sub="Not configured" defaultOn={false} configured={false} />
          </div>
        </div>

        {/* Detection thresholds */}
        <ThresholdsCard />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
        {/* Session / profile */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Session</div>
          </div>
          <div style={{ padding: "0 14px" }}>
            <dl className="props">
              <dt>email</dt>
              <dd className="mono">{session.user.email}</dd>
              <dt>role</dt>
              <dd>
                <span
                  className="mono"
                  style={{
                    fontSize: 10.5,
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                    color: isAdmin ? "var(--accent)" : "var(--text-mute)",
                  }}
                >
                  {role}
                </span>
              </dd>
              <dt>user id</dt>
              <dd className="mono" style={{ color: "var(--text-mute)" }}>
                {session.user.userId || "\u2014"}
              </dd>
              <dt>token expires</dt>
              <dd className="mono" style={{ color: "var(--text-mute)" }}>
                {formatDateTime(expiresAt)}
              </dd>
            </dl>
          </div>
        </div>

        {/* Members */}
        <MembersCard />
      </div>

      {/* FinGuard active model — admin only */}
      {isAdmin && <FinGuardModelCard />}

      {/* Cloud connections — admin only */}
      {isAdmin && <CloudConnectionsCard />}

      {/* Audit log — admin only */}
      {isAdmin && <AuditLogCard />}
    </div>
  );
}

function ChannelRow({ label, sub, defaultOn, configured = true }: {
  label: string; sub: string; defaultOn: boolean; configured?: boolean;
}) {
  const [on, setOn] = useState(defaultOn);
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid var(--border)", opacity: configured ? 1 : 0.45 }}>
      <div>
        <div style={{ fontSize: 12.5 }}>{label}</div>
        <div style={{ fontSize: 11, color: "var(--text-dim)", fontFamily: "var(--mono)" }}>{sub}</div>
      </div>
      <button
        type="button"
        className={`toggle ${on && configured ? "on" : ""}`}
        onClick={() => configured && setOn(!on)}
        style={{ cursor: configured ? "pointer" : "not-allowed" }}
        title={configured ? undefined : "Not configured"}
      >
        <span className="toggle-knob" />
      </button>
    </div>
  );
}

function MembersCard() {
  const { session } = useAuth();
  const { isAdmin, role } = useRole();
  const [users, setUsers] = useState<Array<{ user_id: string; email: string; role: string }>>([]);

  useEffect(() => {
    if (!session || !isAdmin) return;
    apiFetch<{ items: Array<{ user_id: string; email: string; role: string }> }>(
      "/users",
      { token: session.token },
    ).then((r) => setUsers(r.items)).catch(() => {});
  }, [session, isAdmin]);

  const rows = isAdmin
    ? users
    : session ? [{ user_id: session.user.userId ?? "", email: session.user.email, role: role ?? "analyst" }] : [];

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">Members</div>
        <span className="badge-soft">{rows.length}</span>
      </div>
      <div className="card-body">
        {rows.map((u) => (
          <MemberRow key={u.user_id} email={u.email} memberRole={u.role} you={u.email === session?.user.email} />
        ))}
      </div>
    </div>
  );
}

function ThresholdsCard() {
  const { session } = useAuth();
  const { isAdmin } = useRole();
  const [saved_high, setSavedHigh] = useState(0.80);
  const [saved_medium, setSavedMedium] = useState(0.50);
  const [saved_low, setSavedLow] = useState(0.20);
  const [high, setHigh] = useState(0.80);
  const [medium, setMedium] = useState(0.50);
  const [low, setLow] = useState(0.20);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!session) return;
    apiFetch<{ high: number; medium: number; low: number }>(
      "/settings/thresholds",
      { token: session.token },
    ).then((t) => {
      setHigh(t.high); setMedium(t.medium); setLow(t.low);
      setSavedHigh(t.high); setSavedMedium(t.medium); setSavedLow(t.low);
    }).catch(() => {});
  }, [session]);

  const isDirty = high !== saved_high || medium !== saved_medium || low !== saved_low;
  const isOrdered = high > medium && medium > low;

  const handleSave = async () => {
    if (!session || !isOrdered) return;
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const t = await apiFetch<{ high: number; medium: number; low: number }>(
        "/settings/thresholds",
        { method: "PUT", token: session.token, body: { high, medium, low } },
      );
      setHigh(t.high); setMedium(t.medium); setLow(t.low);
      setSavedHigh(t.high); setSavedMedium(t.medium); setSavedLow(t.low);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">Detection thresholds</div>
        {isAdmin && isDirty && (
          <button className="btn sm" type="button" onClick={handleSave} disabled={saving || !isOrdered}>
            {saving ? "Saving…" : saved ? "Saved ✓" : "Save"}
          </button>
        )}
        {isAdmin && !isDirty && saved && (
          <span style={{ fontSize: 11.5, color: "var(--accent)", fontFamily: "var(--mono)" }}>Saved ✓</span>
        )}
      </div>
      <div className="card-body">
        {!isOrdered && (
          <div style={{ marginBottom: 10, fontSize: 12, color: "var(--sev-high)", fontFamily: "var(--mono)" }}>
            Thresholds must be ordered: high &gt; medium &gt; low
          </div>
        )}
        {error && <div style={{ marginBottom: 10, fontSize: 12, color: "var(--sev-high)" }}>{error}</div>}
        <ThresholdSlider label="High severity" value={high} onChange={setHigh} color="var(--sev-high)" disabled={!isAdmin} />
        <ThresholdSlider label="Medium severity" value={medium} onChange={setMedium} color="var(--sev-med)" disabled={!isAdmin} />
        <ThresholdSlider label="Low severity" value={low} onChange={setLow} color="var(--sev-low)" disabled={!isAdmin} />
        <div style={{ marginTop: 4, fontSize: 11, fontFamily: "var(--mono)", color: "var(--text-dim)" }}>
          fusion: 0.45 ts + 0.35 if + 0.20 rules
        </div>
      </div>
    </div>
  );
}

function ThresholdSlider({ label, value, onChange, color, disabled }: {
  label: string; value: number; onChange: (v: number) => void; color: string; disabled?: boolean;
}) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <span style={{ fontSize: 12 }}>{label}</span>
        <span className="mono" style={{ fontSize: 11, color }}>{value.toFixed(2)}</span>
      </div>
      <input
        type="range" min={0} max={1} step={0.01}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        disabled={disabled}
        style={{ width: "100%", accentColor: color, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1 }}
      />
    </div>
  );
}

function MemberRow({ email, memberRole, you }: { email: string; memberRole: string; you?: boolean }) {
  const initials = email.slice(0, 2).toUpperCase();
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
      <div style={{ width: 28, height: 28, borderRadius: "50%", background: "var(--surface-3)", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mono)", fontSize: 10, color: "var(--text-mute)", fontWeight: 600 }}>
        {initials}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12 }}>
          {email}
          {you && <span style={{ marginLeft: 6, fontSize: 10, color: "var(--accent)", fontFamily: "var(--mono)" }}>YOU</span>}
        </div>
      </div>
      <span className="mono" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: "0.04em", color: memberRole === "admin" ? "var(--accent)" : "var(--text-mute)" }}>
        {memberRole}
      </span>
    </div>
  );
}

function FinGuardModelCard() {
  const { session } = useAuth();
  const [profiles, setProfiles] = useState<FinGuardProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [activating, setActivating] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError(null);
    try {
      const res = await listProfiles(session.token);
      setProfiles(res.profiles);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load profiles");
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => { load(); }, [load]);

  const handleActivate = async (id: string) => {
    if (!session) return;
    setActivating(id);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await activateProfile(id, session.token);
      setProfiles(res.profiles);
      const name = res.profiles.find((p) => p.id === id)?.name ?? id;
      setSuccessMsg(`"${name}" is now the live model`);
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to activate");
    } finally {
      setActivating(null);
    }
  };

  const dot = (color: string) => (
    <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: color, flexShrink: 0 }} />
  );

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="card-header">
        <div>
          <div className="card-title">FinGuard — Active model</div>
          <div style={{ fontSize: 11.5, color: "var(--text-dim)", marginTop: 2 }}>
            Select which FinGuard profile reads live billing events for anomaly detection.
          </div>
        </div>
        <button className="btn ghost sm" type="button" onClick={load} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && (
        <div style={{ margin: "0 14px 10px", padding: "8px 10px", background: "var(--sev-high-bg)", border: "1px solid var(--sev-high)", borderRadius: "var(--r-md)", fontSize: 12, color: "var(--sev-high)" }}>
          {error}
        </div>
      )}
      {successMsg && (
        <div style={{ margin: "0 14px 10px", padding: "8px 10px", background: "var(--accent-dim)", border: "1px solid var(--accent)", borderRadius: "var(--r-md)", fontSize: 12, color: "var(--accent)" }}>
          {successMsg}
        </div>
      )}

      <div className="card-body" style={{ display: "grid", gap: 8 }}>
        {profiles.length === 0 && !loading && (
          <div style={{ fontSize: 12, color: "var(--text-mute)", fontFamily: "var(--mono)" }}>
            No profiles found. Go to Model Training to create one.
          </div>
        )}
        {profiles.map((p) => {
          const bothTrained = p.baseline.trained && p.autoencoder.trained;
          const eitherTrained = p.baseline.trained || p.autoencoder.trained;
          const statusColor = bothTrained ? "var(--accent)" : eitherTrained ? "var(--sev-med)" : "var(--sev-high)";
          const statusLabel = bothTrained ? "fully trained" : eitherTrained ? "partial" : "untrained";

          return (
            <div
              key={p.id}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto",
                alignItems: "center",
                gap: 12,
                padding: "10px 12px",
                borderRadius: "var(--r-md)",
                border: `1px solid ${p.active ? "var(--accent)" : "var(--border-faint)"}`,
                background: p.active ? "var(--accent-dim)" : "transparent",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                {dot(statusColor)}
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: p.active ? 700 : 500, color: p.active ? "var(--accent)" : "var(--text-1)" }}>
                      {p.name}
                    </span>
                    {p.active && (
                      <span style={{ fontSize: 9, padding: "1px 6px", borderRadius: 999, background: "var(--accent)", color: "var(--bg-0)", fontFamily: "var(--mono)", fontWeight: 700 }}>
                        LIVE
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 11, fontFamily: "var(--mono)", color: "var(--text-dim)", marginTop: 2 }}>
                    {statusLabel}
                    {p.baseline.trained && p.baseline.last_trained_at && (
                      <span style={{ marginLeft: 8 }}>· baseline {formatRelTime(p.baseline.last_trained_at)}</span>
                    )}
                    {p.autoencoder.trained && p.autoencoder.last_trained_at && (
                      <span style={{ marginLeft: 8 }}>· autoencoder {formatRelTime(p.autoencoder.last_trained_at)}</span>
                    )}
                  </div>
                </div>
              </div>

              {p.active ? (
                <span style={{ fontSize: 11, fontFamily: "var(--mono)", color: "var(--text-mute)" }}>active</span>
              ) : (
                <button
                  className="btn sm"
                  type="button"
                  onClick={() => handleActivate(p.id)}
                  disabled={activating !== null || !bothTrained}
                  title={!bothTrained ? "Profile must be fully trained before activating" : undefined}
                >
                  {activating === p.id ? "Activating…" : "Set live"}
                </button>
              )}
            </div>
          );
        })}

        {profiles.length > 0 && (
          <div style={{ marginTop: 4, fontSize: 11, color: "var(--text-mute)", fontFamily: "var(--mono)" }}>
            Only fully trained profiles can be set live. Train models in the Model Training page.
          </div>
        )}
      </div>
    </div>
  );
}

function CloudConnectionsCard() {
  const { session } = useAuth();
  const token = session?.token ?? null;

  const [status, setStatus] = useState<{ aws: ConnectionStatus; gcp: ConnectionStatus } | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  // AWS form
  const [awsKey, setAwsKey] = useState("");
  const [awsSecret, setAwsSecret] = useState("");
  const [awsRegion, setAwsRegion] = useState("us-east-1");
  const [awsSaving, setAwsSaving] = useState(false);
  const [awsErr, setAwsErr] = useState<string | null>(null);
  const [awsOk, setAwsOk] = useState(false);

  // GCP form
  const [gcpProject, setGcpProject] = useState("");
  const [gcpJson, setGcpJson] = useState("");
  const [gcpSaving, setGcpSaving] = useState(false);
  const [gcpErr, setGcpErr] = useState<string | null>(null);
  const [gcpOk, setGcpOk] = useState(false);

  useEffect(() => {
    if (!token) return;
    fetchConnections(token)
      .then(setStatus)
      .catch((e) => setLoadErr(e.message ?? "Failed to load connections"));
  }, [token]);

  const handleSaveAWS = async () => {
    if (!token) return;
    setAwsSaving(true); setAwsErr(null); setAwsOk(false);
    try {
      const s = await saveAWS({ access_key_id: awsKey, secret_access_key: awsSecret, region: awsRegion }, token);
      setStatus((prev) => prev ? { ...prev, aws: s } : null);
      setAwsKey(""); setAwsSecret("");
      setAwsOk(true);
      setTimeout(() => setAwsOk(false), 2500);
    } catch (e: unknown) {
      setAwsErr(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setAwsSaving(false);
    }
  };

  const handleSaveGCP = async () => {
    if (!token) return;
    setGcpSaving(true); setGcpErr(null); setGcpOk(false);
    try {
      const s = await saveGCP({ project_id: gcpProject, service_account_json: gcpJson }, token);
      setStatus((prev) => prev ? { ...prev, gcp: s } : null);
      setGcpProject(""); setGcpJson("");
      setGcpOk(true);
      setTimeout(() => setGcpOk(false), 2500);
    } catch (e: unknown) {
      setGcpErr(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setGcpSaving(false);
    }
  };

  const handleRemove = async (provider: "aws" | "gcp") => {
    if (!token) return;
    try {
      const s = await removeConnection(provider, token);
      setStatus((prev) => prev ? { ...prev, [provider]: s } : null);
    } catch (e: unknown) {
      /* ignore */
    }
  };

  const dot = (connected: boolean) => (
    <span style={{
      display: "inline-block", width: 7, height: 7, borderRadius: "50%", marginRight: 6,
      background: connected ? "var(--accent)" : "var(--surface-3)",
      border: `1px solid ${connected ? "var(--accent)" : "var(--border-strong)"}`,
    }} />
  );

  const fieldStyle: React.CSSProperties = {
    height: 28, padding: "0 8px", background: "var(--surface-2)",
    border: "1px solid var(--border)", borderRadius: "var(--r-md)",
    color: "var(--text)", fontSize: 12, fontFamily: "var(--mono)", width: "100%",
  };

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="card-header">
        <div className="card-title">Cloud connections</div>
        {loadErr && <span style={{ fontSize: 11.5, color: "var(--sev-high)" }}>{loadErr}</span>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
        {/* AWS */}
        <div style={{ padding: "14px 16px", borderRight: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {dot(status?.aws.connected ?? false)}
              <span style={{ fontSize: 12.5, fontWeight: 600 }}>Amazon Web Services</span>
            </div>
            {status?.aws.connected && (
              <button className="btn ghost sm" type="button" style={{ color: "var(--sev-high)", fontSize: 11 }} onClick={() => handleRemove("aws")}>
                Disconnect
              </button>
            )}
          </div>

          {status?.aws.connected && (
            <div style={{ marginBottom: 12, padding: "8px 10px", background: "var(--surface-2)", borderRadius: "var(--r-md)", border: "1px solid var(--border)" }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--text-mute)", display: "grid", gap: 4 }}>
                <div><span style={{ color: "var(--text-dim)" }}>key </span>{status.aws.masked_key}</div>
                <div><span style={{ color: "var(--text-dim)" }}>region </span>{status.aws.region}</div>
              </div>
            </div>
          )}

          <div style={{ display: "grid", gap: 8 }}>
            <div>
              <div style={{ fontSize: 10.5, fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-mute)", marginBottom: 4 }}>
                Access Key ID
              </div>
              <input style={fieldStyle} type="text" placeholder="AKIA…" value={awsKey} onChange={(e) => setAwsKey(e.target.value)} autoComplete="off" />
            </div>
            <div>
              <div style={{ fontSize: 10.5, fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-mute)", marginBottom: 4 }}>
                Secret Access Key
              </div>
              <input style={fieldStyle} type="password" placeholder="••••••••" value={awsSecret} onChange={(e) => setAwsSecret(e.target.value)} autoComplete="new-password" />
            </div>
            <div>
              <div style={{ fontSize: 10.5, fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-mute)", marginBottom: 4 }}>
                Region
              </div>
              <input style={fieldStyle} type="text" placeholder="us-east-1" value={awsRegion} onChange={(e) => setAwsRegion(e.target.value)} />
            </div>

            {awsErr && <div style={{ fontSize: 11.5, color: "var(--sev-high)" }}>{awsErr}</div>}

            <button
              className="btn primary sm"
              type="button"
              onClick={handleSaveAWS}
              disabled={awsSaving || !awsKey || !awsSecret || !awsRegion}
              style={{ justifyContent: "center" }}
            >
              {awsSaving ? "Saving…" : awsOk ? "Saved ✓" : status?.aws.connected ? "Update" : "Connect"}
            </button>
          </div>
        </div>

        {/* GCP */}
        <div style={{ padding: "14px 16px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {dot(status?.gcp.connected ?? false)}
              <span style={{ fontSize: 12.5, fontWeight: 600 }}>Google Cloud Platform</span>
            </div>
            {status?.gcp.connected && (
              <button className="btn ghost sm" type="button" style={{ color: "var(--sev-high)", fontSize: 11 }} onClick={() => handleRemove("gcp")}>
                Disconnect
              </button>
            )}
          </div>

          {status?.gcp.connected && (
            <div style={{ marginBottom: 12, padding: "8px 10px", background: "var(--surface-2)", borderRadius: "var(--r-md)", border: "1px solid var(--border)" }}>
              <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: "var(--text-mute)", display: "grid", gap: 4 }}>
                <div><span style={{ color: "var(--text-dim)" }}>project </span>{status.gcp.project_id}</div>
              </div>
            </div>
          )}

          <div style={{ display: "grid", gap: 8 }}>
            <div>
              <div style={{ fontSize: 10.5, fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-mute)", marginBottom: 4 }}>
                Project ID
              </div>
              <input style={fieldStyle} type="text" placeholder="my-project-123" value={gcpProject} onChange={(e) => setGcpProject(e.target.value)} autoComplete="off" />
            </div>
            <div>
              <div style={{ fontSize: 10.5, fontFamily: "var(--mono)", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-mute)", marginBottom: 4 }}>
                Service Account JSON
              </div>
              <textarea
                style={{ ...fieldStyle, height: 88, resize: "vertical", padding: "6px 8px", lineHeight: 1.4 }}
                placeholder={'{\n  "type": "service_account",\n  "project_id": "…"\n}'}
                value={gcpJson}
                onChange={(e) => setGcpJson(e.target.value)}
                spellCheck={false}
              />
            </div>

            {gcpErr && <div style={{ fontSize: 11.5, color: "var(--sev-high)" }}>{gcpErr}</div>}

            <button
              className="btn primary sm"
              type="button"
              onClick={handleSaveGCP}
              disabled={gcpSaving || !gcpProject || !gcpJson}
              style={{ justifyContent: "center" }}
            >
              {gcpSaving ? "Saving…" : gcpOk ? "Saved ✓" : status?.gcp.connected ? "Update" : "Connect"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function AuditLogCard() {
  const audit = useAuditLog({ page: 1, page_size: 10 });
  const items = audit.data?.items ?? [];
  const total = audit.data?.total ?? 0;

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-title">Audit log</div>
        <div className="row gap-8" style={{ alignItems: "center" }}>
          <span className="badge-soft">{total} total</span>
          <button className="btn ghost sm" type="button" onClick={audit.reload} disabled={audit.loading}>
            {audit.loading ? "Loading\u2026" : "Refresh"}
          </button>
        </div>
      </div>
      <div className="card-body">
        {audit.error && (
          <div style={{ padding: "8px 0", fontSize: 12, color: "var(--sev-high)" }}>{audit.error}</div>
        )}
        {items.length === 0 && !audit.loading && !audit.error && (
          <div style={{ padding: "14px 0", textAlign: "center", fontSize: 12, color: "var(--text-dim)" }}>No audit entries yet.</div>
        )}
        <div style={{ display: "grid", gap: 4 }}>
          {items.map((entry: AuditLogEntry) => (
            <div key={entry.audit_id} style={{ display: "grid", gridTemplateColumns: "100px 1fr 180px", gap: 8, fontSize: 11.5, fontFamily: "var(--mono)", padding: "4px 0", borderBottom: "1px solid var(--border)" }}>
              <span style={{ color: "var(--text-dim)" }}>{formatRelTime(entry.created_at)}</span>
              <span>
                <span style={{ color: entry.outcome === "failure" ? "var(--sev-high)" : "var(--text-2)" }}>{entry.action}</span>
                {entry.target_id && <span style={{ marginLeft: 6, color: "var(--text-dim)" }}>{entry.target_id}</span>}
              </span>
              <span style={{ color: "var(--text-mute)", textAlign: "right", overflow: "hidden", textOverflow: "ellipsis" }}>{entry.actor_email || "\u2014"}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
