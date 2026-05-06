import { useEffect, useMemo, useState } from "react";
import type { AnomalySeverity, AnomalyStatus } from "./types";

const SEVERITY_OPTIONS: AnomalySeverity[] = ["high", "medium", "low", "none"];
const STATUS_OPTIONS: AnomalyStatus[] = [
  "open",
  "acknowledged",
  "resolved",
  "suppressed",
];

export interface AnomalyFilters {
  accountId: string;
  service: string;
  region: string;
  severity: string;
  status: string;
  fromBucket: string;
  toBucket: string;
}

export const EMPTY_FILTERS: AnomalyFilters = {
  accountId: "",
  service: "",
  region: "",
  severity: "",
  status: "",
  fromBucket: "",
  toBucket: "",
};

interface Props {
  filters: AnomalyFilters;
  onApply: (next: AnomalyFilters) => void;
  onReset: () => void;
  disabled?: boolean;
}

// Convert ISO datetime string to the format <input type="datetime-local"> expects.
// The native control wants "YYYY-MM-DDTHH:mm" with no timezone suffix.
function isoToLocalInput(iso: string): string {
  if (!iso) return "";
  return iso.length >= 16 ? iso.slice(0, 16) : iso;
}

// Convert a local datetime input value back to an ISO string the API accepts.
// Treat the input as UTC (matches how the backend stores buckets) so that
// users see deterministic behavior regardless of browser timezone.
function localInputToIso(local: string): string {
  if (!local) return "";
  return `${local}:00Z`;
}

export default function AnomalyFilterBar({
  filters,
  onApply,
  onReset,
  disabled,
}: Props) {
  const [draft, setDraft] = useState<AnomalyFilters>(filters);

  // When the URL-driven filters change (e.g. user clicks a chip or a KPI link),
  // reset the draft so the form reflects current state.
  useEffect(() => {
    setDraft(filters);
  }, [filters]);

  const activeChips = useMemo(() => buildChips(filters), [filters]);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onApply(draft);
  };

  const handleClearChip = (key: keyof AnomalyFilters) => {
    const next = { ...filters, [key]: "" };
    setDraft(next);
    onApply(next);
  };

  return (
    <form
      className="filter-bar"
      onSubmit={handleSubmit}
      role="search"
      aria-label="Filter anomalies"
    >
      <div className="filter-bar__grid">
        <label className="filter-bar__field">
          <span>Severity</span>
          <select
            value={draft.severity}
            onChange={(e) => setDraft({ ...draft, severity: e.target.value })}
            disabled={disabled}
          >
            <option value="">All</option>
            {SEVERITY_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </label>

        <label className="filter-bar__field">
          <span>Status</span>
          <select
            value={draft.status}
            onChange={(e) => setDraft({ ...draft, status: e.target.value })}
            disabled={disabled}
          >
            <option value="">All</option>
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </label>

        <label className="filter-bar__field">
          <span>Account</span>
          <input
            type="text"
            value={draft.accountId}
            onChange={(e) => setDraft({ ...draft, accountId: e.target.value })}
            placeholder="acct-001"
            disabled={disabled}
          />
        </label>

        <label className="filter-bar__field">
          <span>Service</span>
          <input
            type="text"
            value={draft.service}
            onChange={(e) => setDraft({ ...draft, service: e.target.value })}
            placeholder="BigQuery"
            disabled={disabled}
          />
        </label>

        <label className="filter-bar__field">
          <span>Region</span>
          <input
            type="text"
            value={draft.region}
            onChange={(e) => setDraft({ ...draft, region: e.target.value })}
            placeholder="us-central1"
            disabled={disabled}
          />
        </label>

        <label className="filter-bar__field">
          <span>From (UTC)</span>
          <input
            type="datetime-local"
            value={isoToLocalInput(draft.fromBucket)}
            onChange={(e) =>
              setDraft({ ...draft, fromBucket: localInputToIso(e.target.value) })
            }
            disabled={disabled}
          />
        </label>

        <label className="filter-bar__field">
          <span>To (UTC)</span>
          <input
            type="datetime-local"
            value={isoToLocalInput(draft.toBucket)}
            onChange={(e) =>
              setDraft({ ...draft, toBucket: localInputToIso(e.target.value) })
            }
            disabled={disabled}
          />
        </label>
      </div>

      <div className="filter-bar__actions">
        <button
          type="submit"
          className="filter-bar__apply"
          disabled={disabled}
        >
          Apply filters
        </button>
        <button
          type="button"
          className="filter-bar__reset"
          onClick={onReset}
          disabled={disabled}
        >
          Reset
        </button>
      </div>

      {activeChips.length > 0 ? (
        <ul className="filter-bar__chips" aria-label="Active filters">
          {activeChips.map((chip) => (
            <li key={chip.key}>
              <button
                type="button"
                className="filter-bar__chip"
                onClick={() => handleClearChip(chip.key)}
                aria-label={`Clear ${chip.label} filter`}
                disabled={disabled}
              >
                <span>
                  <strong>{chip.label}:</strong> {chip.value}
                </span>
                <span aria-hidden="true">×</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </form>
  );
}

interface Chip {
  key: keyof AnomalyFilters;
  label: string;
  value: string;
}

function buildChips(filters: AnomalyFilters): Chip[] {
  const chips: Chip[] = [];
  if (filters.severity) chips.push({ key: "severity", label: "Severity", value: filters.severity });
  if (filters.status) chips.push({ key: "status", label: "Status", value: filters.status });
  if (filters.accountId) chips.push({ key: "accountId", label: "Account", value: filters.accountId });
  if (filters.service) chips.push({ key: "service", label: "Service", value: filters.service });
  if (filters.region) chips.push({ key: "region", label: "Region", value: filters.region });
  if (filters.fromBucket) chips.push({ key: "fromBucket", label: "From", value: filters.fromBucket });
  if (filters.toBucket) chips.push({ key: "toBucket", label: "To", value: filters.toBucket });
  return chips;
}
