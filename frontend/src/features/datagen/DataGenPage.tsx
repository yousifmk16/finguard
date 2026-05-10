import { useState } from "react";
import Icon from "@/components/common/Icon";
import { useAuth } from "@/features/auth/useAuth";
import { apiFetch } from "@/lib/api";

interface InjectorConfig {
  enabled: boolean;
  count?: number;
  multiplier?: number;
  start_index?: number;
  slope?: number;
  shift?: number;
  budget_threshold?: number;
  breach_multiplier?: number;
  duration?: number;
}

interface GenConfig {
  n: number;
  seed: string;          // empty = random
  provider: string;
  start_time: string;
  accounts: string;      // comma-separated
  services: string;
  regions: string;
  baseline_default: number;
  spike: InjectorConfig;
  drift: InjectorConfig;
  level_shift: InjectorConfig;
  budget_breach: InjectorConfig;
}

interface GenResult {
  accepted: number;
  duplicate: number;
  failed: number;
  total: number;
  anomalies_seeded: number;
  alerts_seeded: number;
  seed_used: number;
}

interface DeleteResult {
  events_deleted: number;
  anomalies_deleted: number;
  alerts_deleted: number;
}

const DEFAULTS: GenConfig = {
  n: 240,
  seed: "",
  provider: "gcp",
  start_time: "2026-04-09",
  accounts: "acct-prod-1, acct-prod-2, acct-dev-1",
  services: "Compute Engine, Cloud Storage, BigQuery",
  regions: "us-central1, us-east1, europe-west1",
  baseline_default: 120,
  spike:        { enabled: true,  count: 6,   multiplier: 2.8 },
  drift:        { enabled: true,  start_index: 120, slope: 0.003 },
  level_shift:  { enabled: true,  start_index: 180, shift: 40 },
  budget_breach:{ enabled: true,  start_index: 200, duration: 10, budget_threshold: 220, breach_multiplier: 1.1 },
};

export default function DataGenPage() {
  const { session } = useAuth();
  const [cfg, setCfg] = useState<GenConfig>(DEFAULTS);
  const [running, setRunning] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [result, setResult] = useState<GenResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof GenConfig>(key: K, val: GenConfig[K]) =>
    setCfg((c) => ({ ...c, [key]: val }));

  const setInj = (inj: keyof Pick<GenConfig, "spike" | "drift" | "level_shift" | "budget_breach">, patch: Partial<InjectorConfig>) =>
    setCfg((c) => ({ ...c, [inj]: { ...c[inj], ...patch } }));

  const buildPayload = () => ({
    n: cfg.n,
    seed: cfg.seed ? parseInt(cfg.seed) : null,
    provider: cfg.provider,
    start_time: cfg.start_time + "T00:00:00Z",
    accounts: cfg.accounts.split(",").map((s) => s.trim()).filter(Boolean),
    services: cfg.services.split(",").map((s) => s.trim()).filter(Boolean),
    regions: cfg.regions.split(",").map((s) => s.trim()).filter(Boolean),
    baseline_default: cfg.baseline_default,
    spike: cfg.spike,
    drift: cfg.drift,
    level_shift: cfg.level_shift,
    budget_breach: cfg.budget_breach,
  });

  const handleGenerate = async () => {
    if (!session) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<GenResult>("/admin/generate", {
        method: "POST",
        token: session.token,
        body: buildPayload(),
      });
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const handleClear = async () => {
    if (!session) return;
    setClearing(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiFetch<DeleteResult>("/admin/data", {
        method: "DELETE",
        token: session.token,
      });
      setError(null);
      setResult({ accepted: 0, duplicate: 0, failed: 0, total: 0, anomalies_seeded: 0, alerts_seeded: 0, seed_used: 0 });
      setError(`Cleared — ${res.events_deleted} events, ${res.anomalies_deleted} anomalies, ${res.alerts_deleted} alerts deleted`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setClearing(false);
    }
  };

  const handleReset = () => setCfg(DEFAULTS);

  return (
    <div className="page fade-in">
      <div className="page-header">
        <div>
          <h1 className="page-title">Data generator</h1>
          <div className="page-sub">Synthetic billing events with configurable anomaly injection.</div>
        </div>
        <div className="page-actions">
          <button className="btn ghost sm" type="button" onClick={handleReset}>Reset defaults</button>
          <button
            className="btn ghost sm"
            type="button"
            onClick={handleClear}
            disabled={clearing || running}
            style={{ color: "var(--sev-high)", borderColor: "var(--sev-high)" }}
          >
            {clearing ? "Clearing…" : "Clear all data"}
          </button>
          <button className="btn" type="button" onClick={handleGenerate} disabled={running || clearing}>
            <Icon name="sparkles" size={14} />
            {running ? "Generating…" : "Run generator"}
          </button>
        </div>
      </div>

      {/* Result / error banner */}
      {result && result.total > 0 && (
        <div style={{ padding: "10px 16px", background: "var(--accent-dim)", border: "1px solid var(--accent)", borderRadius: "var(--r-md)", marginBottom: 14, fontSize: 12.5, color: "var(--accent)", display: "flex", gap: 24, alignItems: "center" }}>
          <span><b>{result.accepted}</b> events ingested</span>
          <span><b>{result.anomalies_seeded}</b> anomalies seeded</span>
          <span><b>{result.alerts_seeded}</b> alerts seeded</span>
          {result.duplicate > 0 && <span style={{ color: "var(--text-mute)" }}>{result.duplicate} duplicate</span>}
          {result.failed > 0 && <span style={{ color: "var(--sev-high)" }}>{result.failed} failed</span>}
          <span style={{ marginLeft: "auto", color: "var(--text-dim)", fontFamily: "var(--mono)", fontSize: 11 }}>seed {result.seed_used}</span>
        </div>
      )}
      {error && (
        <div style={{ padding: "10px 16px", background: "var(--sev-high-bg)", border: "1px solid var(--sev-high)", borderRadius: "var(--r-md)", marginBottom: 14, fontSize: 12.5, color: "var(--sev-high)" }}>
          {error}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        {/* Left: basic settings */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card">
            <div className="card-header"><div className="card-title">Basic settings</div></div>
            <div className="card-body" style={{ display: "grid", gap: 12 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <Field label="Events (n)">
                  <input className="input" type="number" min={1} max={2000} value={cfg.n}
                    onChange={(e) => set("n", parseInt(e.target.value) || 240)} />
                </Field>
                <Field label="Seed (blank = random)">
                  <input className="input" type="number" value={cfg.seed}
                    onChange={(e) => set("seed", e.target.value)}
                    placeholder="random" />
                </Field>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <Field label="Provider">
                  <select className="select" value={cfg.provider} onChange={(e) => set("provider", e.target.value)}>
                    <option value="gcp">GCP</option>
                    <option value="aws">AWS</option>
                    <option value="azure">Azure</option>
                  </select>
                </Field>
                <Field label="Start date">
                  <input className="input" type="date" value={cfg.start_time}
                    onChange={(e) => set("start_time", e.target.value)} />
                </Field>
              </div>
              <Field label="Baseline cost ($/event)">
                <input className="input" type="number" min={1} value={cfg.baseline_default}
                  onChange={(e) => set("baseline_default", parseFloat(e.target.value) || 120)} />
              </Field>
            </div>
          </div>

          <div className="card">
            <div className="card-header"><div className="card-title">Accounts, services, regions</div></div>
            <div className="card-body" style={{ display: "grid", gap: 12 }}>
              <Field label="Accounts (comma-separated)">
                <input className="input" value={cfg.accounts}
                  onChange={(e) => set("accounts", e.target.value)}
                  placeholder="acct-prod-1, acct-prod-2" />
              </Field>
              <Field label="Services">
                <input className="input" value={cfg.services}
                  onChange={(e) => set("services", e.target.value)}
                  placeholder="Compute Engine, Cloud Storage" />
              </Field>
              <Field label="Regions">
                <input className="input" value={cfg.regions}
                  onChange={(e) => set("regions", e.target.value)}
                  placeholder="us-central1, us-east1" />
              </Field>
            </div>
          </div>
        </div>

        {/* Right: anomaly injectors */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <InjectorCard
            title="Spike"
            sub="Multiplies cost by a factor at random indices"
            color="var(--sev-high)"
            cfg={cfg.spike}
            onChange={(p) => setInj("spike", p)}
          >
            <Field label="Count">
              <input className="input" type="number" min={1} max={50} value={cfg.spike.count}
                onChange={(e) => setInj("spike", { count: parseInt(e.target.value) || 6 })} />
            </Field>
            <Field label="Multiplier">
              <input className="input" type="number" min={1.1} step={0.1} value={cfg.spike.multiplier}
                onChange={(e) => setInj("spike", { multiplier: parseFloat(e.target.value) || 2.8 })} />
            </Field>
          </InjectorCard>

          <InjectorCard
            title="Drift"
            sub="Gradual upward cost creep from a start index"
            color="var(--sev-med)"
            cfg={cfg.drift}
            onChange={(p) => setInj("drift", p)}
          >
            <Field label="Start index">
              <input className="input" type="number" min={0} value={cfg.drift.start_index}
                onChange={(e) => setInj("drift", { start_index: parseInt(e.target.value) || 120 })} />
            </Field>
            <Field label="Slope">
              <input className="input" type="number" step={0.001} value={cfg.drift.slope}
                onChange={(e) => setInj("drift", { slope: parseFloat(e.target.value) || 0.003 })} />
            </Field>
          </InjectorCard>

          <InjectorCard
            title="Level shift"
            sub="Permanent cost step-up from a start index"
            color="var(--sev-med)"
            cfg={cfg.level_shift}
            onChange={(p) => setInj("level_shift", p)}
          >
            <Field label="Start index">
              <input className="input" type="number" min={0} value={cfg.level_shift.start_index}
                onChange={(e) => setInj("level_shift", { start_index: parseInt(e.target.value) || 180 })} />
            </Field>
            <Field label="Shift ($)">
              <input className="input" type="number" min={0} value={cfg.level_shift.shift}
                onChange={(e) => setInj("level_shift", { shift: parseFloat(e.target.value) || 40 })} />
            </Field>
          </InjectorCard>

          <InjectorCard
            title="Budget breach"
            sub="Sustained overspend above a threshold"
            color="var(--sev-low)"
            cfg={cfg.budget_breach}
            onChange={(p) => setInj("budget_breach", p)}
          >
            <Field label="Start index">
              <input className="input" type="number" min={0} value={cfg.budget_breach.start_index}
                onChange={(e) => setInj("budget_breach", { start_index: parseInt(e.target.value) || 200 })} />
            </Field>
            <Field label="Duration (events)">
              <input className="input" type="number" min={1} value={cfg.budget_breach.duration}
                onChange={(e) => setInj("budget_breach", { duration: parseInt(e.target.value) || 10 })} />
            </Field>
            <Field label="Budget threshold ($)">
              <input className="input" type="number" min={0} value={cfg.budget_breach.budget_threshold}
                onChange={(e) => setInj("budget_breach", { budget_threshold: parseFloat(e.target.value) || 220 })} />
            </Field>
            <Field label="Breach multiplier">
              <input className="input" type="number" min={1} step={0.05} value={cfg.budget_breach.breach_multiplier}
                onChange={(e) => setInj("budget_breach", { breach_multiplier: parseFloat(e.target.value) || 1.1 })} />
            </Field>
          </InjectorCard>
        </div>
      </div>
    </div>
  );
}

function InjectorCard({ title, sub, color, cfg, onChange, children }: {
  title: string;
  sub: string;
  color: string;
  cfg: InjectorConfig;
  onChange: (p: Partial<InjectorConfig>) => void;
  children: React.ReactNode;
}) {
  return (
    <div className="card" style={{ borderLeft: `3px solid ${cfg.enabled ? color : "var(--border)"}`, transition: "border-color 0.15s" }}>
      <div className="card-header">
        <div>
          <div className="card-title" style={{ color: cfg.enabled ? color : "var(--text-mute)" }}>{title}</div>
          <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 2 }}>{sub}</div>
        </div>
        <button type="button" className={`toggle ${cfg.enabled ? "on" : ""}`} onClick={() => onChange({ enabled: !cfg.enabled })}>
          <span className="toggle-knob" />
        </button>
      </div>
      {cfg.enabled && (
        <div className="card-body" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          {children}
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "grid", gap: 5 }}>
      <label style={{ fontSize: 10.5, fontFamily: "var(--mono)", color: "var(--text-mute)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </label>
      {children}
    </div>
  );
}
