import { Link, useParams } from "react-router-dom";
import SeverityBadge from "@/components/common/SeverityBadge";
import StatusBadge from "@/components/common/StatusBadge";
import { formatDateTime, formatScore } from "@/lib/formatters";
import StatusActions from "./StatusActions";
import { useAnomaly, type AnomalyDetailState } from "./useAnomaly";
import type { AnomalyRecord } from "./types";

export default function AnomalyDetailPage() {
  const { anomalyId } = useParams<{ anomalyId: string }>();
  const detail = useAnomaly(anomalyId);
  const { data, loading, error, notFound, reload } = detail;

  return (
    <section className="anomaly-detail">
      <Breadcrumbs anomalyId={anomalyId} />

      {loading && !data ? (
        <div className="state-banner" role="status">
          Loading anomaly...
        </div>
      ) : null}

      {notFound ? (
        <div className="state-banner state-banner--error" role="alert">
          <span>Anomaly {anomalyId} could not be found.</span>
          <Link to="/anomalies">Back to list</Link>
        </div>
      ) : null}

      {error && !notFound ? (
        <div className="state-banner state-banner--error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={reload}>
            Try again
          </button>
        </div>
      ) : null}

      {data ? <AnomalyDetailContent anomaly={data} detail={detail} /> : null}
    </section>
  );
}

function Breadcrumbs({ anomalyId }: { anomalyId: string | undefined }) {
  return (
    <nav className="anomaly-detail__breadcrumbs" aria-label="Breadcrumb">
      <ol>
        <li>
          <Link to="/dashboard">Dashboard</Link>
        </li>
        <li>
          <Link to="/anomalies">Anomalies</Link>
        </li>
        <li aria-current="page">{anomalyId ?? "-"}</li>
      </ol>
      <Link to="/anomalies" className="anomaly-detail__back">
        Back to list
      </Link>
    </nav>
  );
}

function AnomalyDetailContent({
  anomaly,
  detail,
}: {
  anomaly: AnomalyRecord;
  detail: AnomalyDetailState;
}) {
  const breakdownEntries = Object.entries(anomaly.score_breakdown ?? {});
  const explanation = pluckExplanation(anomaly.score_breakdown);

  return (
    <>
      <header className="anomaly-detail__header">
        <div className="anomaly-detail__title">
          <h1>{anomaly.anomaly_id}</h1>
          <div className="anomaly-detail__title-badges">
            <SeverityBadge severity={anomaly.severity} />
            <StatusBadge status={anomaly.status} />
          </div>
        </div>
        <dl className="anomaly-detail__summary">
          <Field label="Account" value={anomaly.account_id} />
          <Field label="Service" value={anomaly.service} />
          <Field label="Region" value={anomaly.region} />
          <Field label="Bucket" value={formatDateTime(anomaly.bucket)} />
          <Field label="Detected" value={formatDateTime(anomaly.detected_at)} />
        </dl>
      </header>

      <div className="anomaly-detail__grid">
        <section className="card">
          <header className="card__header">
            <h2>Score Summary</h2>
          </header>
          <p className="anomaly-detail__final-score">
            <span>Final score</span>
            <strong>{formatScore(anomaly.anomaly_score)}</strong>
          </p>
          {breakdownEntries.length > 0 ? (
            <dl className="anomaly-detail__breakdown">
              {breakdownEntries
                .filter(([key]) => key !== "explanation")
                .map(([key, value]) => (
                  <Field key={key} label={prettifyKey(key)} value={renderBreakdownValue(value)} />
                ))}
            </dl>
          ) : (
            <p className="card__empty">Score breakdown not available for this anomaly.</p>
          )}
          {explanation ? (
            <p className="anomaly-detail__explanation">{explanation}</p>
          ) : null}
        </section>

        <section className="card">
          <header className="card__header">
            <h2>Lifecycle Actions</h2>
          </header>
          <StatusActions
            current={anomaly.status}
            mutating={detail.mutating}
            mutationError={detail.mutationError}
            onUpdate={detail.updateStatus}
            onClearError={detail.clearMutationError}
          />
        </section>

        <section className="card">
          <header className="card__header">
            <h2>Related Alerts</h2>
            <span className="card__task-tag">UI-07</span>
          </header>
          <p className="card__empty">
            Per-anomaly alert linkage is owned by UI-07. The alerts API filters by
            account/service/region today; an <code>anomaly_id</code> filter will
            land alongside the alert center page.
          </p>
        </section>
      </div>
    </>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="field">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function prettifyKey(key: string): string {
  return key
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function renderBreakdownValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return formatScore(value, 3);
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function pluckExplanation(breakdown: Record<string, unknown> | null | undefined): string | null {
  if (!breakdown) return null;
  const value = breakdown.explanation;
  return typeof value === "string" && value.length > 0 ? value : null;
}
