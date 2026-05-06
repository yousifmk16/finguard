import { useEffect, useMemo, useState } from "react";
import type { AlertChannel, AlertSeverity, AlertStatus } from "./types";

const SEVERITY_OPTIONS: AlertSeverity[] = ["high", "medium", "low", "none"];
const STATUS_OPTIONS: AlertStatus[] = ["pending", "sent", "failed", "suppressed"];
const CHANNEL_OPTIONS: AlertChannel[] = ["in_app", "email"];

export interface AlertFilters {
  accountId: string;
  service: string;
  region: string;
  severity: string;
  status: string;
  channel: string;
}

export const EMPTY_ALERT_FILTERS: AlertFilters = {
  accountId: "",
  service: "",
  region: "",
  severity: "",
  status: "",
  channel: "",
};

interface Props {
  filters: AlertFilters;
  onApply: (next: AlertFilters) => void;
  onReset: () => void;
  disabled?: boolean;
}

export default function AlertFilterBar({
  filters,
  onApply,
  onReset,
  disabled,
}: Props) {
  const [draft, setDraft] = useState<AlertFilters>(filters);

  useEffect(() => {
    setDraft(filters);
  }, [filters]);

  const chips = useMemo(() => buildChips(filters), [filters]);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onApply(draft);
  };

  const clearChip = (key: keyof AlertFilters) => {
    const next = { ...filters, [key]: "" };
    setDraft(next);
    onApply(next);
  };

  return (
    <form
      className="filter-bar"
      onSubmit={handleSubmit}
      role="search"
      aria-label="Filter alerts"
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
              <option key={opt} value={opt}>{opt}</option>
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
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </label>

        <label className="filter-bar__field">
          <span>Channel</span>
          <select
            value={draft.channel}
            onChange={(e) => setDraft({ ...draft, channel: e.target.value })}
            disabled={disabled}
          >
            <option value="">All</option>
            {CHANNEL_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>{opt.replace("_", "-")}</option>
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
      </div>

      <div className="filter-bar__actions">
        <button type="submit" className="filter-bar__apply" disabled={disabled}>
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

      {chips.length > 0 ? (
        <ul className="filter-bar__chips" aria-label="Active filters">
          {chips.map((c) => (
            <li key={c.key}>
              <button
                type="button"
                className="filter-bar__chip"
                onClick={() => clearChip(c.key)}
                aria-label={`Clear ${c.label} filter`}
                disabled={disabled}
              >
                <span>
                  <strong>{c.label}:</strong> {c.value}
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
  key: keyof AlertFilters;
  label: string;
  value: string;
}

function buildChips(filters: AlertFilters): Chip[] {
  const chips: Chip[] = [];
  if (filters.severity) chips.push({ key: "severity", label: "Severity", value: filters.severity });
  if (filters.status) chips.push({ key: "status", label: "Status", value: filters.status });
  if (filters.channel) chips.push({ key: "channel", label: "Channel", value: filters.channel });
  if (filters.accountId) chips.push({ key: "accountId", label: "Account", value: filters.accountId });
  if (filters.service) chips.push({ key: "service", label: "Service", value: filters.service });
  if (filters.region) chips.push({ key: "region", label: "Region", value: filters.region });
  return chips;
}
