import { Link, useParams } from "react-router-dom";
import Icon from "@/components/common/Icon";
import SeverityBadge from "@/components/common/SeverityBadge";
import StatusBadge from "@/components/common/StatusBadge";
import { formatDateTime, formatMoney, formatPct } from "@/lib/formatters";
import StatusActions from "./StatusActions";
import { useAnomaly } from "./useAnomaly";
import type { AnomalyRecord } from "./types";

export default function AnomalyDetailPage() {
  const { anomalyId } = useParams<{ anomalyId: string }>();
  const detail = useAnomaly(anomalyId);
  const { data, loading, error, notFound, reload } = detail;

  if (loading && !data) {
    return (
      <div className="page">
        <div className="empty"><div className="big">LOADING\u2026</div></div>
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="page">
        <div className="empty">
          <div className="big">NOT FOUND</div>
          <div style={{ marginTop: 8 }}><Link to="/anomalies">Back to list</Link></div>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="page">
        <div style={{ padding: 14, background: "var(--sev-high-bg)", border: "1px solid var(--sev-high)", borderRadius: "var(--r-md)", color: "var(--sev-high)" }}>
          {error}
          <button className="btn sm" style={{ marginLeft: 12 }} onClick={reload} type="button">Retry</button>
        </div>
      </div>
    );
  }

  if (!data) return null;

  return <DetailContent anomaly={data} detail={detail} />;
}

function DetailContent({ anomaly: a, detail }: { anomaly: AnomalyRecord; detail: ReturnType<typeof useAnomaly> }) {
  const breakdown = a.score_breakdown as Record<string, number> | null | undefined;
  const tsSignal = breakdown?.ts_signal ?? 0;
  const ifScore = breakdown?.if_score ?? 0;
  const ruleScore = breakdown?.rule_score ?? 0;

  const scoreColor = a.severity === "high" ? "var(--sev-high)" : a.severity === "medium" ? "var(--sev-med)" : a.severity === "low" ? "var(--sev-low)" : "var(--text-mute)";
  const r = 56;
  const c = 2 * Math.PI * r;
  const off = c * (1 - a.anomaly_score);

  return (
    <div className="page fade-in">
      <div className="page-header">
        <div>
          <Link to="/anomalies" className="btn ghost sm" style={{ marginBottom: 8 }}>
            <Icon name="chevron-left" size={12} /> Anomalies
          </Link>
          <div className="row gap-12" style={{ alignItems: "center" }}>
            <h1 className="page-title">{a.service} · {a.region}</h1>
            <SeverityBadge severity={a.severity} />
            <StatusBadge status={a.status} />
          </div>
          <div className="page-sub mono">
            id <span style={{ color: "var(--text-2)" }}>{a.anomaly_id}</span>
          </div>
        </div>
        <div className="page-actions">
          <StatusActions
            current={a.status}
            mutating={detail.mutating}
            mutationError={detail.mutationError}
            onUpdate={detail.updateStatus}
            onClearError={detail.clearMutationError}
          />
        </div>
      </div>

      <div className="detail-grid" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="card-header">
            <div className="card-title">Hybrid score · explainability</div>
            <span className="badge-soft" style={{ borderColor: "var(--accent)", color: "var(--accent)" }}>FUSED</span>
          </div>
          <div className="score-hero">
            <div className="score-ring">
              <svg width="132" height="132">
                <circle cx="66" cy="66" r={r} stroke="var(--surface-3)" strokeWidth="8" fill="none" />
                <circle cx="66" cy="66" r={r} stroke={scoreColor} strokeWidth="8" fill="none"
                  strokeDasharray={c} strokeDashoffset={off} strokeLinecap="round" />
              </svg>
              <div className="num">
                <div>{a.anomaly_score.toFixed(2)}</div>
                <small>SCORE</small>
              </div>
            </div>
            <div className="score-bars">
              <ScoreBarRow label="TS signal" value={tsSignal} cls="ts" />
              <ScoreBarRow label="Iso forest" value={ifScore} cls="if" />
              <ScoreBarRow label="Rules" value={ruleScore} cls="rl" />
              <div style={{ marginTop: 6, fontFamily: "var(--mono)", fontSize: 11, color: "var(--text-mute)" }}>
                fusion: 0.45·ts + 0.35·if + 0.20·rules → <span style={{ color: "var(--text)" }}>{a.anomaly_score.toFixed(3)}</span>
              </div>
            </div>
          </div>
        </div>

        <div className="col" style={{ gap: 14 }}>
          <div className="card">
            <div className="card-header"><div className="card-title">Properties</div></div>
            <div style={{ padding: "0 14px" }}>
              <dl className="props">
                <dt>account</dt><dd className="mono">{a.account_id}</dd>
                <dt>service</dt><dd>{a.service}</dd>
                <dt>region</dt><dd className="mono">{a.region}</dd>
                <dt>bucket</dt><dd className="mono">{formatDateTime(a.bucket)}</dd>
                <dt>detected</dt><dd className="mono">{formatDateTime(a.detected_at)}</dd>
                {a.observed_cost != null && (
                  <><dt>cost</dt><dd className="mono">{formatMoney(a.observed_cost)}</dd></>
                )}
                {a.baseline_cost != null && (
                  <><dt>baseline</dt><dd className="mono" style={{ color: "var(--text-mute)" }}>
                    {formatMoney(a.baseline_cost)}
                    {a.delta_pct != null && (
                      <span style={{ color: (a.delta_pct ?? 0) > 0 ? "var(--sev-high)" : "var(--accent)", marginLeft: 6 }}>
                        ({formatPct(a.delta_pct)})
                      </span>
                    )}
                  </dd></>
                )}
              </dl>
            </div>
          </div>

          <div className="card">
            <div className="card-header"><div className="card-title">Timeline</div></div>
            <div style={{ padding: "10px 14px" }}>
              <div className="timeline">
                <div className="tl-item evt-detect">
                  <div className="tl-dot" />
                  <div className="tl-body">
                    <div className="ttl">
                      Detected · score <span className="mono">{a.anomaly_score.toFixed(2)}</span> · severity{" "}
                      <span style={{ color: scoreColor }}>{a.severity}</span>
                    </div>
                    <div className="meta">{formatDateTime(a.detected_at)}</div>
                  </div>
                </div>
                {(a.status === "acknowledged" || a.status === "resolved") && (
                  <div className="tl-item evt-ack">
                    <div className="tl-dot" />
                    <div className="tl-body">
                      <div className="ttl">Acknowledged</div>
                    </div>
                  </div>
                )}
                {a.status === "resolved" && (
                  <div className="tl-item evt-resolve">
                    <div className="tl-dot" />
                    <div className="tl-body">
                      <div className="ttl">Resolved · cause attributed</div>
                    </div>
                  </div>
                )}
                {a.status === "suppressed" && (
                  <div className="tl-item evt-resolve">
                    <div className="tl-dot" />
                    <div className="tl-body">
                      <div className="ttl">Suppressed · marked as expected</div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Raw event JSON */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">Raw event</div>
        </div>
        <div className="card-body">
          <pre style={{ margin: 0, fontFamily: "var(--mono)", fontSize: 12, color: "var(--text-2)", whiteSpace: "pre-wrap" }}>
            {JSON.stringify({
              anomaly_id: a.anomaly_id,
              account_id: a.account_id,
              service: a.service,
              region: a.region,
              bucket: a.bucket,
              anomaly_score: a.anomaly_score,
              severity: a.severity,
              status: a.status,
              detected_at: a.detected_at,
              score_breakdown: a.score_breakdown,
            }, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
}

function ScoreBarRow({ label, value, cls }: { label: string; value: number; cls: string }) {
  return (
    <div className="score-bar-row">
      <div className="lbl">{label}</div>
      <div className={`score-bar ${cls}`}>
        <div className="fill" style={{ width: `${value * 100}%` }} />
      </div>
      <div className="val">{value.toFixed(2)}</div>
    </div>
  );
}
