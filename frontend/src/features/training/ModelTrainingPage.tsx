import { useCallback, useEffect, useRef, useState } from "react";
import Icon from "@/components/common/Icon";
import { useAuth } from "@/features/auth/useAuth";
import { apiFetch } from "@/lib/api";
import { useTrainingStatus } from "./useTrainingStatus";
import {
  uploadTrainingData, exportTrainingData, getTrainingData,
  listProfiles, createProfile, renameProfile, deleteProfile,
} from "./training-api";
import { formatRelTime } from "@/lib/formatters";
import type {
  TrainResult, UploadResult, TrainingDataPage,
  FinGuardProfile,
} from "./training-api";

// ---------------------------------------------------------------------------
// Data-gen types
// ---------------------------------------------------------------------------

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
  seed: string;
  provider: string;
  start_time: string;
  accounts: string;
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
  seed_used: number;
}

interface DeleteResult {
  events_deleted: number;
}

const GEN_DEFAULTS: GenConfig = {
  n: 240,
  seed: "",
  provider: "gcp",
  start_time: "2026-04-09",
  accounts: "acct-prod-1, acct-prod-2, acct-dev-1",
  services: "Compute Engine, Cloud Storage, BigQuery",
  regions: "us-central1, us-east1, europe-west1",
  baseline_default: 120,
  spike:         { enabled: true, count: 6,   multiplier: 2.8 },
  drift:         { enabled: true, start_index: 120, slope: 0.003 },
  level_shift:   { enabled: true, start_index: 180, shift: 40 },
  budget_breach: { enabled: true, start_index: 200, duration: 10, budget_threshold: 220, breach_multiplier: 1.1 },
};

// ---------------------------------------------------------------------------
// Model-training types
// ---------------------------------------------------------------------------

interface ModelConfig {
  lookback_days: number;
  min_train_rows: number;
}

const MODEL_DEFAULTS: ModelConfig = { lookback_days: 30, min_train_rows: 60 };

type DataSource = "all" | "generated" | "uploaded";
type DataTab = "generate" | "upload" | "view";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ModelTrainingPage() {
  const { session } = useAuth();
  const status = useTrainingStatus();

  // ── data tab ──
  const [dataTab, setDataTab] = useState<DataTab>("generate");

  // ── data gen state ──
  const [cfg, setCfg] = useState<GenConfig>(GEN_DEFAULTS);
  const [generating, setGenerating] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [genResult, setGenResult] = useState<GenResult | null>(null);
  const [genError, setGenError] = useState<string | null>(null);
  const [clearMsg, setClearMsg] = useState<string | null>(null);

  // ── upload state ──
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  // ── export state ──
  const [exporting, setExporting] = useState(false);

  // ── view data state ──
  const [viewPage, setViewPage] = useState(1);
  const [viewSource, setViewSource] = useState<DataSource>("all");
  const [viewData, setViewData] = useState<TrainingDataPage | null>(null);
  const [viewLoading, setViewLoading] = useState(false);
  const [viewError, setViewError] = useState<string | null>(null);

  // ── model training state ──
  const [dataSource, setDataSource] = useState<DataSource>("all");
  const [modelCfg, setModelCfg] = useState<ModelConfig>(MODEL_DEFAULTS);
  const [training, setTraining] = useState(false);
  const [trainResults, setTrainResults] = useState<{ baseline: TrainResult | null; ae: TrainResult | null } | null>(null);
  const [trainError, setTrainError] = useState<string | null>(null);

  // ── profile state ──
  const [profiles, setProfiles] = useState<FinGuardProfile[]>([]);
  const [profilesLoading, setProfilesLoading] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(null);
  const [creatingProfile, setCreatingProfile] = useState(false);
  const [newProfileName, setNewProfileName] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [savingRename, setSavingRename] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // Fetch training data whenever view tab is active, page or source changes
  const fetchViewData = useCallback(() => {
    if (!session || dataTab !== "view") return;
    const controller = new AbortController();
    setViewLoading(true);
    setViewError(null);
    getTrainingData({ page: viewPage, page_size: 50, source: viewSource }, session.token, controller.signal)
      .then(setViewData)
      .catch((e) => { if (e?.name !== "AbortError") setViewError(e instanceof Error ? e.message : String(e)); })
      .finally(() => setViewLoading(false));
    return () => controller.abort();
  }, [session, dataTab, viewPage, viewSource]);

  useEffect(() => {
    const cleanup = fetchViewData();
    return cleanup;
  }, [fetchViewData]);

  // ── profile loader ──
  const loadProfiles = useCallback(async () => {
    if (!session) return;
    setProfilesLoading(true);
    setProfileError(null);
    try {
      const res = await listProfiles(session.token);
      setProfiles(res.profiles);
      // Auto-select the active (live) profile if nothing is selected yet
      const trainable = res.profiles.filter((p) => p.id !== "default");
      setSelectedProfileId((prev) => {
        if (prev && trainable.some((p) => p.id === prev)) return prev;
        return trainable.find((p) => p.active)?.id ?? trainable[0]?.id ?? null;
      });
    } catch (e: unknown) {
      setProfileError(e instanceof Error ? e.message : String(e));
    } finally {
      setProfilesLoading(false);
    }
  }, [session]);

  useEffect(() => { loadProfiles(); }, [loadProfiles]);

  // ── profile handlers ──
  const handleSelectProfile = (id: string) => {
    setSelectedProfileId(id);
    setTrainResults(null);
    setTrainError(null);
  };

  const handleCreateProfile = async () => {
    if (!session || !newProfileName.trim()) return;
    setSavingProfile(true);
    setProfileError(null);
    try {
      await createProfile(newProfileName.trim(), session.token);
      setNewProfileName("");
      setCreatingProfile(false);
      await loadProfiles();
    } catch (e: unknown) {
      setProfileError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingProfile(false);
    }
  };

  const handleRenameProfile = async (id: string) => {
    if (!session || !renameValue.trim()) return;
    setSavingRename(true);
    setProfileError(null);
    try {
      await renameProfile(id, renameValue.trim(), session.token);
      setRenamingId(null);
      setRenameValue("");
      await loadProfiles();
    } catch (e: unknown) {
      setProfileError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingRename(false);
    }
  };

  const handleDeleteProfile = async (id: string) => {
    if (!session) return;
    setDeletingId(id);
    setProfileError(null);
    try {
      const res = await deleteProfile(id, session.token);
      setProfiles(res.profiles);
    } catch (e: unknown) {
      setProfileError(e instanceof Error ? e.message : String(e));
    } finally {
      setDeletingId(null);
    }
  };

  const anyRunning = generating || clearing || uploading || training;

  // ── data gen helpers ──
  const set = <K extends keyof GenConfig>(key: K, val: GenConfig[K]) =>
    setCfg((c) => ({ ...c, [key]: val }));

  const setInj = (
    inj: keyof Pick<GenConfig, "spike" | "drift" | "level_shift" | "budget_breach">,
    patch: Partial<InjectorConfig>,
  ) => setCfg((c) => ({ ...c, [inj]: { ...c[inj], ...patch } }));

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
    setGenerating(true);
    setGenError(null);
    setGenResult(null);
    setClearMsg(null);
    try {
      const res = await apiFetch<GenResult>("/admin/generate", {
        method: "POST",
        token: session.token,
        body: { ...buildPayload(), mode: "training" },
      });
      setGenResult(res);
      status.reload();
      setViewPage(1);
    } catch (e: unknown) {
      setGenError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  };

  const handleClear = async () => {
    if (!session) return;
    setClearing(true);
    setGenError(null);
    setGenResult(null);
    setClearMsg(null);
    setUploadResult(null);
    setUploadError(null);
    try {
      const res = await apiFetch<DeleteResult>("/admin/data?mode=training", {
        method: "DELETE",
        token: session.token,
      });
      setClearMsg(`Cleared — ${res.events_deleted} training events deleted`);
      status.reload();
      setViewPage(1);
      setViewData(null);
    } catch (e: unknown) {
      setGenError(e instanceof Error ? e.message : String(e));
    } finally {
      setClearing(false);
    }
  };

  // ── upload handler ──
  const handleUpload = async () => {
    if (!session || !selectedFile) return;
    setUploading(true);
    setUploadError(null);
    setUploadResult(null);
    try {
      const res = await uploadTrainingData(selectedFile, session.token);
      setUploadResult(res);
      setSelectedFile(null);
      if (fileRef.current) fileRef.current.value = "";
      status.reload();
      setViewPage(1);
    } catch (e: unknown) {
      setUploadError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  };

  // ── export handler ──
  const handleExport = async () => {
    if (!session) return;
    setExporting(true);
    try {
      await exportTrainingData(session.token);
    } catch (e: unknown) {
      setGenError(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  };

  // ── model training handler ──
  const handleTrainFinGuard = async () => {
    if (!session) return;
    setTraining(true);
    setTrainResults(null);
    setTrainError(null);
    let baselineRes: TrainResult | null = null;
    let aeRes: TrainResult | null = null;
    const errors: string[] = [];
    const trainBody = { ...modelCfg, data_source: dataSource, profile_id: selectedProfileId ?? undefined };
    try {
      baselineRes = await apiFetch<TrainResult>("/admin/train/baseline", {
        method: "POST",
        token: session.token,
        body: trainBody,
      });
    } catch (e: unknown) {
      errors.push(`Baseline: ${e instanceof Error ? e.message : String(e)}`);
    }
    try {
      aeRes = await apiFetch<TrainResult>("/admin/train/autoencoder", {
        method: "POST",
        token: session.token,
        body: trainBody,
      });
    } catch (e: unknown) {
      errors.push(`Autoencoder: ${e instanceof Error ? e.message : String(e)}`);
    }
    setTrainResults({ baseline: baselineRes, ae: aeRes });
    if (errors.length) setTrainError(errors.join(" · "));
    await loadProfiles();
    status.reload();
    setTraining(false);
  };

  const ds = status.data?.data;

  return (
    <div className="page fade-in">
      {/* ── Page header ── */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Model training</h1>
          <div className="page-sub">
            Train on Google Cloud Billing data — generate synthetic data, upload your own export, or both.
          </div>
        </div>
        <div className="page-actions">
          <button
            className="btn ghost sm"
            type="button"
            onClick={status.reload}
            disabled={anyRunning || status.loading}
          >
            {status.loading ? "Refreshing…" : "Refresh status"}
          </button>
        </div>
      </div>

      {/* ════════════════════════════════════════════════════
          STEP 1 — Training data
      ════════════════════════════════════════════════════ */}
      <SectionHeader
        step={1}
        title="Training data"
        sub="GCP Cloud Billing seed data is loaded automatically. You can also upload your own billing export or generate more."
      />

      {/* Data stats bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 20,
          padding: "8px 14px",
          marginBottom: 14,
          background: "var(--bg-2)",
          borderRadius: "var(--r-md)",
          border: "1px solid var(--border-faint)",
          fontSize: 12,
        }}
      >
        <StatChip label="Generated" value={ds?.generated ?? 0} />
        <StatChip label="Uploaded" value={ds?.uploaded ?? 0} />
        <StatChip label="Total" value={ds?.total ?? 0} accent />
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button
            className="btn ghost sm"
            type="button"
            onClick={handleExport}
            disabled={anyRunning || exporting || !ds?.total}
          >
            {exporting ? "Exporting…" : "Export CSV"}
          </button>
          <button
            className="btn ghost sm"
            type="button"
            onClick={handleClear}
            disabled={anyRunning || !ds?.total}
            style={{ color: "var(--sev-high)", borderColor: "var(--sev-high)" }}
          >
            {clearing ? "Clearing…" : "Clear all"}
          </button>
        </div>
      </div>

      {/* Global banners */}
      {clearMsg && <Banner variant="info">{clearMsg}</Banner>}
      {genError && <Banner variant="error">{genError}</Banner>}

      {/* Data tabs */}
      <div style={{ display: "flex", gap: 0, marginBottom: 14, borderBottom: "1px solid var(--border-faint)" }}>
        <TabBtn active={dataTab === "generate"} onClick={() => setDataTab("generate")}>
          Generate
        </TabBtn>
        <TabBtn active={dataTab === "upload"} onClick={() => setDataTab("upload")}>
          Upload CSV
        </TabBtn>
        <TabBtn active={dataTab === "view"} onClick={() => { setDataTab("view"); setViewPage(1); }}>
          View Data
          {ds && ds.total > 0 && (
            <span style={{ marginLeft: 6, fontFamily: "var(--mono)", fontSize: 10, opacity: 0.7 }}>
              {ds.total.toLocaleString()}
            </span>
          )}
        </TabBtn>
      </div>

      {/* ── Generate tab ── */}
      {dataTab === "generate" && (
        <>
          {genResult && genResult.accepted > 0 && (
            <Banner variant="success">
              <b>{genResult.accepted}</b> training events generated — ready to train models below
              {genResult.duplicate > 0 && (
                <span style={{ marginLeft: 12, color: "var(--text-mute)" }}>{genResult.duplicate} duplicate</span>
              )}
              {genResult.failed > 0 && (
                <span style={{ marginLeft: 12, color: "var(--sev-high)" }}>{genResult.failed} failed</span>
              )}
              <span style={{ marginLeft: "auto", fontFamily: "var(--mono)", fontSize: 11, color: "var(--text-dim)" }}>
                seed {genResult.seed_used}
              </span>
            </Banner>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 28 }}>
            {/* Left: basic settings */}
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div className="card">
                <div className="card-header">
                  <div className="card-title">Basic settings</div>
                  <button
                    className="btn ghost sm"
                    type="button"
                    onClick={() => setCfg(GEN_DEFAULTS)}
                    disabled={anyRunning}
                  >
                    Reset
                  </button>
                </div>
                <div className="card-body" style={{ display: "grid", gap: 12 }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    <Field label="Events (n)">
                      <input className="input" type="number" min={1} max={2000} value={cfg.n}
                        onChange={(e) => set("n", parseInt(e.target.value) || 240)} />
                    </Field>
                    <Field label="Seed (blank = random)">
                      <input className="input" type="number" value={cfg.seed}
                        onChange={(e) => set("seed", e.target.value)} placeholder="random" />
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
              <InjectorCard title="Spike" sub="Multiplies cost by a factor at random indices"
                color="var(--sev-high)" cfg={cfg.spike} onChange={(p) => setInj("spike", p)}>
                <Field label="Count">
                  <input className="input" type="number" min={1} max={50} value={cfg.spike.count}
                    onChange={(e) => setInj("spike", { count: parseInt(e.target.value) || 6 })} />
                </Field>
                <Field label="Multiplier">
                  <input className="input" type="number" min={1.1} step={0.1} value={cfg.spike.multiplier}
                    onChange={(e) => setInj("spike", { multiplier: parseFloat(e.target.value) || 2.8 })} />
                </Field>
              </InjectorCard>

              <InjectorCard title="Drift" sub="Gradual upward cost creep from a start index"
                color="var(--sev-med)" cfg={cfg.drift} onChange={(p) => setInj("drift", p)}>
                <Field label="Start index">
                  <input className="input" type="number" min={0} value={cfg.drift.start_index}
                    onChange={(e) => setInj("drift", { start_index: parseInt(e.target.value) || 120 })} />
                </Field>
                <Field label="Slope">
                  <input className="input" type="number" step={0.001} value={cfg.drift.slope}
                    onChange={(e) => setInj("drift", { slope: parseFloat(e.target.value) || 0.003 })} />
                </Field>
              </InjectorCard>

              <InjectorCard title="Level shift" sub="Permanent cost step-up from a start index"
                color="var(--sev-med)" cfg={cfg.level_shift} onChange={(p) => setInj("level_shift", p)}>
                <Field label="Start index">
                  <input className="input" type="number" min={0} value={cfg.level_shift.start_index}
                    onChange={(e) => setInj("level_shift", { start_index: parseInt(e.target.value) || 180 })} />
                </Field>
                <Field label="Shift ($)">
                  <input className="input" type="number" min={0} value={cfg.level_shift.shift}
                    onChange={(e) => setInj("level_shift", { shift: parseFloat(e.target.value) || 40 })} />
                </Field>
              </InjectorCard>

              <InjectorCard title="Budget breach" sub="Sustained overspend above a threshold"
                color="var(--sev-low)" cfg={cfg.budget_breach} onChange={(p) => setInj("budget_breach", p)}>
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

          <div style={{ marginBottom: 28 }}>
            <button className="btn" type="button" onClick={handleGenerate} disabled={anyRunning}>
              <Icon name="sparkles" size={14} />
              {generating ? "Generating…" : "Generate training data"}
            </button>
          </div>
        </>
      )}

      {/* ── Upload tab ── */}
      {dataTab === "upload" && (
        <div style={{ marginBottom: 28 }}>
          <div className="card">
            <div className="card-header"><div className="card-title">Upload CSV file</div></div>
            <div className="card-body" style={{ display: "grid", gap: 14 }}>
              <div style={{ fontSize: 12, color: "var(--text-dim)", lineHeight: 1.5 }}>
                <b>GCP Cloud Billing export:</b> auto-detected — columns like{" "}
                <code>usage_start_time</code>, <code>project.id</code>, <code>service.description</code>,{" "}
                <code>location.region</code>, <code>cost</code> are mapped automatically. Tax/adjustment rows are skipped.
                <br />
                <b>FinGuard format:</b>{" "}
                <code>timestamp</code>, <code>account_id</code>, <code>service</code>,{" "}
                <code>region</code>, <code>cost_amount</code>, <code>usage_amount</code>
                <br />
                Timestamps should be ISO 8601 (e.g. <code>2026-04-10T12:00:00Z</code>).
              </div>

              <div
                style={{
                  border: "2px dashed var(--border)",
                  borderRadius: "var(--r-md)",
                  padding: "24px 16px",
                  textAlign: "center",
                  cursor: "pointer",
                  transition: "border-color 0.15s",
                  ...(selectedFile ? { borderColor: "var(--accent)" } : {}),
                }}
                onClick={() => fileRef.current?.click()}
              >
                <input
                  ref={fileRef}
                  type="file"
                  accept=".csv,text/csv"
                  style={{ display: "none" }}
                  onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
                />
                {selectedFile ? (
                  <div style={{ color: "var(--accent)", fontSize: 13 }}>
                    <b>{selectedFile.name}</b>
                    <span style={{ marginLeft: 8, color: "var(--text-dim)" }}>
                      ({(selectedFile.size / 1024).toFixed(1)} KB)
                    </span>
                  </div>
                ) : (
                  <div style={{ color: "var(--text-mute)", fontSize: 13 }}>
                    Click to select a CSV file or drag and drop
                  </div>
                )}
              </div>

              <button
                className="btn"
                type="button"
                onClick={handleUpload}
                disabled={anyRunning || !selectedFile}
                style={{ justifySelf: "start" }}
              >
                {uploading ? "Uploading…" : "Upload and add to training data"}
              </button>
            </div>
          </div>

          {uploadResult && (
            <Banner variant={uploadResult.failed > 0 ? "error" : "success"}>
              <b>{uploadResult.accepted}</b> rows uploaded
              {uploadResult.failed > 0 && (
                <span style={{ marginLeft: 8 }}>· {uploadResult.failed} failed</span>
              )}
              {uploadResult.errors.length > 0 && (
                <span style={{ marginLeft: 8, fontSize: 11, color: "var(--text-dim)" }}>
                  — {uploadResult.errors[0]}
                  {uploadResult.errors.length > 1 && ` (+${uploadResult.errors.length - 1} more)`}
                </span>
              )}
            </Banner>
          )}
          {uploadError && <Banner variant="error">{uploadError}</Banner>}
        </div>
      )}

      {/* ── View Data tab ── */}
      {dataTab === "view" && (
        <div style={{ marginBottom: 28 }}>
          {/* source filter + refresh */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
            <span style={{ fontSize: 10.5, fontFamily: "var(--mono)", color: "var(--text-mute)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Source
            </span>
            {(["all", "generated", "uploaded"] as DataSource[]).map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => { setViewSource(s); setViewPage(1); }}
                style={{
                  padding: "3px 10px",
                  fontSize: 11.5,
                  fontFamily: "var(--mono)",
                  borderRadius: 999,
                  border: `1px solid ${viewSource === s ? "var(--accent)" : "var(--border)"}`,
                  background: viewSource === s ? "var(--accent-dim)" : "transparent",
                  color: viewSource === s ? "var(--accent)" : "var(--text-dim)",
                  cursor: "pointer",
                }}
              >
                {s}
              </button>
            ))}
            <button
              className="btn ghost sm"
              type="button"
              style={{ marginLeft: "auto" }}
              onClick={fetchViewData}
              disabled={viewLoading}
            >
              {viewLoading ? "Loading…" : "Refresh"}
            </button>
          </div>

          {viewError && <Banner variant="error">{viewError}</Banner>}

          {!viewData || viewData.total === 0 ? (
            <div style={{ padding: "32px 16px", textAlign: "center", color: "var(--text-mute)", fontSize: 13, fontFamily: "var(--mono)" }}>
              {viewLoading ? "Loading…" : "No training data yet — generate or upload data first."}
            </div>
          ) : (
            <>
              <div style={{ overflowX: "auto", borderRadius: "var(--r-md)", border: "1px solid var(--border-faint)" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, fontFamily: "var(--mono)" }}>
                  <thead>
                    <tr style={{ background: "var(--bg-2)", borderBottom: "1px solid var(--border-faint)" }}>
                      {["Timestamp", "Provider", "Account", "Service", "Region", "Cost ($)", "Usage", "Unit", "Source"].map((h) => (
                        <th key={h} style={{ padding: "7px 10px", textAlign: "left", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-dim)", fontWeight: 600, whiteSpace: "nowrap" }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {viewData.rows.map((row, i) => (
                      <tr
                        key={i}
                        style={{ borderBottom: "1px solid var(--border-faint)", background: i % 2 === 0 ? "transparent" : "var(--bg-1)" }}
                      >
                        <td style={{ padding: "6px 10px", color: "var(--text-dim)", whiteSpace: "nowrap" }}>{row.timestamp.replace("T", " ").slice(0, 19)}</td>
                        <td style={{ padding: "6px 10px", color: "var(--text-1)" }}>{row.provider}</td>
                        <td style={{ padding: "6px 10px", color: "var(--text-1)", maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.account_id}</td>
                        <td style={{ padding: "6px 10px", color: "var(--text-1)", maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.service}</td>
                        <td style={{ padding: "6px 10px", color: "var(--text-1)" }}>{row.region}</td>
                        <td style={{ padding: "6px 10px", color: "var(--text-1)", textAlign: "right" }}>{row.cost_amount.toFixed(4)}</td>
                        <td style={{ padding: "6px 10px", color: "var(--text-1)", textAlign: "right" }}>{row.usage_amount.toFixed(4)}</td>
                        <td style={{ padding: "6px 10px", color: "var(--text-dim)" }}>{row.usage_unit}</td>
                        <td style={{ padding: "6px 10px" }}>
                          <span style={{
                            fontSize: 10,
                            padding: "2px 6px",
                            borderRadius: 999,
                            border: `1px solid ${row.source === "generated" ? "var(--accent)" : "var(--sev-med)"}`,
                            color: row.source === "generated" ? "var(--accent)" : "var(--sev-med)",
                          }}>
                            {row.source}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 10, fontSize: 12, color: "var(--text-dim)" }}>
                <span>
                  {((viewPage - 1) * 50 + 1).toLocaleString()}–{Math.min(viewPage * 50, viewData.total).toLocaleString()} of {viewData.total.toLocaleString()} rows
                </span>
                <div style={{ display: "flex", gap: 6 }}>
                  <button
                    className="btn ghost sm"
                    type="button"
                    disabled={viewPage <= 1 || viewLoading}
                    onClick={() => setViewPage((p) => p - 1)}
                  >
                    ← Prev
                  </button>
                  <span style={{ padding: "4px 8px", fontFamily: "var(--mono)", fontSize: 11 }}>
                    {viewPage} / {viewData.pages}
                  </span>
                  <button
                    className="btn ghost sm"
                    type="button"
                    disabled={viewPage >= viewData.pages || viewLoading}
                    onClick={() => setViewPage((p) => p + 1)}
                  >
                    Next →
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* ════════════════════════════════════════════════════
          STEP 2 — Train models
      ════════════════════════════════════════════════════ */}
      <SectionHeader
        step={2}
        title="Train models"
        sub="Fit the anomaly detection models on training data."
      />

      {/* Data source selector */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          marginBottom: 14,
          fontSize: 12.5,
        }}
      >
        <span style={{ color: "var(--text-dim)", fontFamily: "var(--mono)", fontSize: 10.5, textTransform: "uppercase", letterSpacing: "0.06em" }}>
          Data source
        </span>
        <RadioPill label="All" value="all" selected={dataSource} onSelect={setDataSource}
          count={ds?.total} />
        <RadioPill label="Generated" value="generated" selected={dataSource} onSelect={setDataSource}
          count={ds?.generated} />
        <RadioPill label="Uploaded" value="uploaded" selected={dataSource} onSelect={setDataSource}
          count={ds?.uploaded} />
      </div>

      {status.error && <Banner variant="error">{status.error}</Banner>}
      {profileError && <Banner variant="error">{profileError}</Banner>}

      {/* ── Profile selector ── */}
      <div style={{ marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {profilesLoading && profiles.length === 0 ? (
            <span style={{ fontSize: 12, color: "var(--text-mute)", fontFamily: "var(--mono)" }}>Loading profiles…</span>
          ) : (
            profiles.filter((p) => p.id !== "default").map((p) => (
              <ProfilePill
                key={p.id}
                profile={p}
                selected={selectedProfileId === p.id}
                renaming={renamingId === p.id}
                renameValue={renamingId === p.id ? renameValue : ""}
                savingRename={savingRename}
                deleting={deletingId === p.id}
                disabled={anyRunning}
                onSelect={() => handleSelectProfile(p.id)}
                onStartRename={() => { setRenamingId(p.id); setRenameValue(p.name); setProfileError(null); }}
                onRenameChange={setRenameValue}
                onRenameCommit={() => handleRenameProfile(p.id)}
                onRenameCancel={() => { setRenamingId(null); setRenameValue(""); }}
                onDelete={() => handleDeleteProfile(p.id)}
              />
            ))
          )}

          {/* Create new profile */}
          {creatingProfile ? (
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <input
                className="input"
                style={{ padding: "3px 8px", fontSize: 12, width: 140, height: 28 }}
                placeholder="Profile name"
                value={newProfileName}
                autoFocus
                onChange={(e) => setNewProfileName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreateProfile();
                  if (e.key === "Escape") { setCreatingProfile(false); setNewProfileName(""); }
                }}
              />
              <button
                className="btn sm"
                type="button"
                onClick={handleCreateProfile}
                disabled={savingProfile || !newProfileName.trim()}
                style={{ padding: "3px 10px", fontSize: 12 }}
              >
                {savingProfile ? "…" : "Save"}
              </button>
              <button
                className="btn ghost sm"
                type="button"
                onClick={() => { setCreatingProfile(false); setNewProfileName(""); }}
                style={{ padding: "3px 8px", fontSize: 12 }}
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => { setCreatingProfile(true); setProfileError(null); }}
              disabled={anyRunning}
              style={{
                padding: "3px 10px",
                fontSize: 11.5,
                fontFamily: "var(--mono)",
                borderRadius: 999,
                border: "1px dashed var(--border)",
                background: "transparent",
                color: "var(--text-mute)",
                cursor: "pointer",
              }}
            >
              + New
            </button>
          )}
        </div>
      </div>

      <FinGuardCard
        profile={profiles.find((p) => p.id === selectedProfileId) ?? null}
        loading={profilesLoading}
        results={trainResults}
        error={trainError}
        training={training}
        cfg={modelCfg}
        onCfgChange={setModelCfg}
        onTrain={handleTrainFinGuard}
        disabled={anyRunning || !selectedProfileId}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// SectionHeader
// ---------------------------------------------------------------------------

function SectionHeader({ step, title, sub }: { step: number; title: string; sub: string }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        marginBottom: 14,
        paddingBottom: 10,
        borderBottom: "1px solid var(--border-faint)",
      }}
    >
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 22,
          height: 22,
          borderRadius: "50%",
          background: "var(--accent)",
          color: "var(--bg-0)",
          fontSize: 11,
          fontFamily: "var(--mono)",
          fontWeight: 700,
          flexShrink: 0,
        }}
      >
        {step}
      </span>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-1)" }}>{title}</div>
        <div style={{ fontSize: 11.5, color: "var(--text-dim)", marginTop: 2 }}>{sub}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TabBtn
// ---------------------------------------------------------------------------

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        padding: "8px 16px",
        fontSize: 12.5,
        fontWeight: active ? 600 : 400,
        color: active ? "var(--accent)" : "var(--text-dim)",
        background: "none",
        border: "none",
        borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
        cursor: "pointer",
        transition: "color 0.15s, border-color 0.15s",
      }}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// RadioPill
// ---------------------------------------------------------------------------

function RadioPill({
  label,
  value,
  selected,
  onSelect,
  count,
}: {
  label: string;
  value: DataSource;
  selected: DataSource;
  onSelect: (v: DataSource) => void;
  count?: number;
}) {
  const active = selected === value;
  return (
    <button
      type="button"
      onClick={() => onSelect(value)}
      style={{
        padding: "4px 12px",
        fontSize: 12,
        fontFamily: "var(--mono)",
        borderRadius: 999,
        border: `1px solid ${active ? "var(--accent)" : "var(--border)"}`,
        background: active ? "var(--accent-dim)" : "transparent",
        color: active ? "var(--accent)" : "var(--text-dim)",
        cursor: "pointer",
        transition: "all 0.15s",
      }}
    >
      {label}
      {count != null && (
        <span style={{ marginLeft: 6, opacity: 0.7 }}>{count.toLocaleString()}</span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// StatChip
// ---------------------------------------------------------------------------

function StatChip({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ fontSize: 10.5, fontFamily: "var(--mono)", color: "var(--text-mute)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </span>
      <span style={{
        fontSize: 13,
        fontWeight: accent ? 700 : 500,
        fontFamily: "var(--mono)",
        color: accent ? "var(--accent)" : "var(--text-1)",
      }}>
        {value.toLocaleString()}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ProfilePill
// ---------------------------------------------------------------------------

function ProfilePill({
  profile,
  selected,
  renaming,
  renameValue,
  savingRename,
  deleting,
  disabled,
  onSelect,
  onStartRename,
  onRenameChange,
  onRenameCommit,
  onRenameCancel,
  onDelete,
}: {
  profile: FinGuardProfile;
  selected: boolean;
  renaming: boolean;
  renameValue: string;
  savingRename: boolean;
  deleting: boolean;
  disabled: boolean;
  onSelect: () => void;
  onStartRename: () => void;
  onRenameChange: (v: string) => void;
  onRenameCommit: () => void;
  onRenameCancel: () => void;
  onDelete: () => void;
}) {
  const bothTrained = profile.baseline.trained && profile.autoencoder.trained;
  const eitherTrained = profile.baseline.trained || profile.autoencoder.trained;
  const dotColor = bothTrained
    ? "var(--accent)"
    : eitherTrained
    ? "var(--sev-med)"
    : "var(--sev-high)";

  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "3px 6px 3px 10px",
        borderRadius: 999,
        border: `1px solid ${selected ? "var(--accent)" : "var(--border)"}`,
        background: selected ? "var(--accent-dim)" : "var(--bg-2)",
        fontSize: 12,
        fontFamily: "var(--mono)",
        cursor: selected ? "default" : "pointer",
      }}
      onClick={selected ? undefined : onSelect}
    >
      {/* Status dot */}
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: dotColor, flexShrink: 0, marginRight: 4 }} />

      {/* Name / rename input */}
      {renaming ? (
        <input
          className="input"
          style={{ padding: "1px 6px", fontSize: 12, width: 120, height: 22, borderRadius: 4 }}
          value={renameValue}
          autoFocus
          onChange={(e) => onRenameChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onRenameCommit();
            if (e.key === "Escape") onRenameCancel();
          }}
        />
      ) : (
        <span
          style={{
            color: selected ? "var(--accent)" : "var(--text-1)",
            fontWeight: selected ? 600 : 400,
            maxWidth: 140,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {profile.name}
        </span>
      )}

      {/* "live" badge shown if this profile is the active inference model */}
      {profile.active && !renaming && (
        <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 999, background: "var(--sev-med)", color: "#fff", marginLeft: 2, opacity: 0.85 }}>
          live
        </span>
      )}

      {/* Rename action buttons */}
      {renaming ? (
        <>
          <button type="button" onClick={onRenameCommit} disabled={savingRename || !renameValue.trim()}
            style={{ marginLeft: 2, background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "var(--accent)", padding: "0 3px" }}>
            {savingRename ? "…" : "✓"}
          </button>
          <button type="button" onClick={onRenameCancel}
            style={{ background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "var(--text-mute)", padding: "0 3px" }}>
            ✕
          </button>
        </>
      ) : (
        <>
          {/* Edit / rename — hidden for the Default profile */}
          {profile.id !== "default" && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onStartRename(); }}
              disabled={disabled}
              title="Rename"
              style={{ background: "none", border: "none", cursor: "pointer", padding: "0 3px", color: "var(--text-mute)", fontSize: 11, lineHeight: 1 }}
            >
              ✏
            </button>
          )}
          {/* Delete — blocked for Default profile and live profile */}
          {profile.id !== "default" && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onDelete(); }}
              disabled={disabled || profile.active || deleting}
              title={profile.active ? "Cannot delete the live model — change it in Settings first" : "Delete profile"}
              style={{
                background: "none", border: "none", cursor: profile.active ? "not-allowed" : "pointer",
                padding: "0 3px", color: profile.active ? "var(--border)" : "var(--sev-high)", fontSize: 11, lineHeight: 1,
                opacity: profile.active ? 0.4 : 1,
              }}
            >
              {deleting ? "…" : "✕"}
            </button>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// FinGuardCard — combined model card for the UI
// ---------------------------------------------------------------------------

function FinGuardCard({
  profile,
  loading,
  results,
  error,
  training,
  cfg,
  onCfgChange,
  onTrain,
  disabled,
}: {
  profile: FinGuardProfile | null;
  loading: boolean;
  results: { baseline: TrainResult | null; ae: TrainResult | null } | null;
  error: string | null;
  training: boolean;
  cfg: ModelConfig;
  onCfgChange: (c: ModelConfig) => void;
  onTrain: () => void;
  disabled: boolean;
}) {
  const baselineArtifact = profile?.baseline ?? null;
  const aeArtifact = profile?.autoencoder ?? null;
  const bothTrained = (baselineArtifact?.trained ?? false) && (aeArtifact?.trained ?? false);
  const eitherTrained = (baselineArtifact?.trained ?? false) || (aeArtifact?.trained ?? false);

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      <div className="card-header">
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div className="card-title" style={{ fontSize: 15, fontWeight: 700 }}>FinGuard</div>
            {profile && (
              <span style={{ fontSize: 11, fontFamily: "var(--mono)", color: "var(--text-dim)", fontWeight: 400 }}>
                / {profile.name}
              </span>
            )}
          </div>
          <div style={{ fontSize: 11.5, color: "var(--text-dim)", marginTop: 2 }}>
            Ensemble anomaly detector — combines a time-series baseline with an autoencoder to score billing anomalies.
          </div>
        </div>
        <span
          className="badge-soft"
          style={
            loading
              ? { color: "var(--text-mute)" }
              : bothTrained
              ? { borderColor: "var(--accent)", color: "var(--accent)" }
              : eitherTrained
              ? { borderColor: "var(--sev-med)", color: "var(--sev-med)" }
              : { borderColor: "var(--sev-high)", color: "var(--sev-high)" }
          }
        >
          {loading ? "…" : bothTrained ? "trained" : eitherTrained ? "partial" : "untrained"}
        </span>
      </div>

      {/* Artifact stats — two sub-sections side by side */}
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border-faint)", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        {/* Time-series baseline */}
        <div>
          <div style={{ fontSize: 10, fontFamily: "var(--mono)", color: "var(--text-mute)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
            Time-series baseline
          </div>
          {loading && !baselineArtifact ? (
            <div style={{ fontSize: 11.5, color: "var(--text-mute)", fontFamily: "var(--mono)" }}>loading…</div>
          ) : baselineArtifact?.trained ? (
            <div style={{ display: "grid", gap: "5px 14px" }}>
              <StatRow label="Last trained" value={baselineArtifact.last_trained_at ? formatRelTime(baselineArtifact.last_trained_at) : "—"} />
              <StatRow label="Train rows" value={baselineArtifact.train_rows > 0 ? baselineArtifact.train_rows.toLocaleString() : "—"} />
              {baselineArtifact.version && <StatRow label="Version" value={baselineArtifact.version} mono />}
            </div>
          ) : (
            <div style={{ fontSize: 11.5, color: "var(--text-mute)", fontFamily: "var(--mono)" }}>not trained</div>
          )}
        </div>

        {/* Autoencoder */}
        <div>
          <div style={{ fontSize: 10, fontFamily: "var(--mono)", color: "var(--text-mute)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
            Autoencoder
          </div>
          {loading && !aeArtifact ? (
            <div style={{ fontSize: 11.5, color: "var(--text-mute)", fontFamily: "var(--mono)" }}>loading…</div>
          ) : aeArtifact?.trained ? (
            <div style={{ display: "grid", gap: "5px 14px" }}>
              <StatRow label="Last trained" value={aeArtifact.last_trained_at ? formatRelTime(aeArtifact.last_trained_at) : "—"} />
              <StatRow label="Train rows" value={aeArtifact.train_rows > 0 ? aeArtifact.train_rows.toLocaleString() : "—"} />
              {aeArtifact.extra?.feature_count != null && (
                <StatRow label="Features" value={String(aeArtifact.extra.feature_count)} />
              )}
              {aeArtifact.version && <StatRow label="Version" value={aeArtifact.version} mono />}
            </div>
          ) : (
            <div style={{ fontSize: 11.5, color: "var(--text-mute)", fontFamily: "var(--mono)" }}>not trained</div>
          )}
        </div>
      </div>

      {/* Shared config */}
      <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--border-faint)", display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <Field label="Lookback days">
          <input
            className="input"
            type="number"
            min={1}
            max={365}
            value={cfg.lookback_days}
            onChange={(e) => onCfgChange({ ...cfg, lookback_days: parseInt(e.target.value) || 30 })}
          />
        </Field>
        <Field label="Min train rows">
          <input
            className="input"
            type="number"
            min={1}
            value={cfg.min_train_rows}
            onChange={(e) => onCfgChange({ ...cfg, min_train_rows: parseInt(e.target.value) || 60 })}
          />
        </Field>
      </div>

      {results && (results.baseline || results.ae) && (
        <Banner variant="success">
          {results.baseline && (
            <span>
              Baseline: <b>{results.baseline.train_rows.toLocaleString()}</b> rows in <b>{results.baseline.elapsed_seconds}s</b>
            </span>
          )}
          {results.baseline && results.ae && <span style={{ margin: "0 8px", opacity: 0.4 }}>·</span>}
          {results.ae && (
            <span>
              Autoencoder: <b>{results.ae.train_rows.toLocaleString()}</b> rows in <b>{results.ae.elapsed_seconds}s</b>
            </span>
          )}
        </Banner>
      )}
      {error && <Banner variant="error">{error}</Banner>}

      <div style={{ padding: "10px 14px" }}>
        <button
          className="btn"
          type="button"
          style={{ width: "100%" }}
          onClick={onTrain}
          disabled={disabled}
        >
          {training ? "Training FinGuard…" : "Train FinGuard"}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// InjectorCard
// ---------------------------------------------------------------------------

function InjectorCard({
  title,
  sub,
  color,
  cfg,
  onChange,
  children,
}: {
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
        <button
          type="button"
          className={`toggle ${cfg.enabled ? "on" : ""}`}
          onClick={() => onChange({ enabled: !cfg.enabled })}
        >
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

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function StatRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div style={{ fontSize: 10, fontFamily: "var(--mono)", color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontSize: 12, fontFamily: mono ? "var(--mono)" : undefined, color: "var(--text-1)" }}>
        {value}
      </div>
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

function Banner({
  variant,
  children,
}: {
  variant: "success" | "error" | "info";
  children: React.ReactNode;
}) {
  const colors = {
    success: { bg: "var(--accent-dim)", border: "var(--accent)", text: "var(--accent)" },
    error:   { bg: "var(--sev-high-bg)", border: "var(--sev-high)", text: "var(--sev-high)" },
    info:    { bg: "var(--bg-2)", border: "var(--border)", text: "var(--text-dim)" },
  }[variant];

  return (
    <div
      style={{
        padding: "9px 14px",
        background: colors.bg,
        border: `1px solid ${colors.border}`,
        borderRadius: "var(--r-md)",
        marginBottom: 14,
        fontSize: 12.5,
        color: colors.text,
        display: "flex",
        alignItems: "center",
        gap: 8,
      }}
    >
      {children}
    </div>
  );
}
