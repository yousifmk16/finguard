import { useState } from "react";
import StatusBadge from "@/components/common/StatusBadge";
import type { AnomalyStatus } from "./types";

interface Props {
  current: AnomalyStatus | string;
  mutating: boolean;
  mutationError: string | null;
  onUpdate: (next: AnomalyStatus) => Promise<unknown>;
  onClearError: () => void;
}

interface Action {
  status: AnomalyStatus;
  label: string;
  variant: "primary" | "success" | "muted" | "neutral";
  /** Tooltip / aria-label describing the lifecycle effect. */
  description: string;
  /** When true, prompt for confirmation — used for terminal transitions. */
  confirm?: boolean;
}

const ALL_ACTIONS: Action[] = [
  {
    status: "acknowledged",
    label: "Acknowledge",
    variant: "primary",
    description: "Mark this anomaly as seen by an operator",
  },
  {
    status: "resolved",
    label: "Resolve",
    variant: "success",
    description: "Confirm and close this anomaly",
    confirm: true,
  },
  {
    status: "suppressed",
    label: "Suppress",
    variant: "muted",
    description: "Silence as a known false-positive",
    confirm: true,
  },
  {
    status: "open",
    label: "Reopen",
    variant: "neutral",
    description: "Re-open this anomaly for review",
  },
];

// Hide the "transition to current state" button — there's no point showing
// "Acknowledge" when the anomaly is already acknowledged.
function visibleActions(current: string): Action[] {
  return ALL_ACTIONS.filter((a) => a.status !== current);
}

export default function StatusActions({
  current,
  mutating,
  mutationError,
  onUpdate,
  onClearError,
}: Props) {
  const [pending, setPending] = useState<AnomalyStatus | null>(null);
  const actions = visibleActions(current);

  const handleClick = async (action: Action) => {
    if (action.confirm) {
      const ok = window.confirm(
        `${action.description}?\n\nThis will set status to "${action.status}".`,
      );
      if (!ok) return;
    }
    setPending(action.status);
    try {
      await onUpdate(action.status);
    } finally {
      setPending(null);
    }
  };

  return (
    <div className="status-actions">
      <div className="status-actions__current">
        <span className="status-actions__label">Current status</span>
        <StatusBadge status={current} />
      </div>

      {mutationError ? (
        <div
          className="state-banner state-banner--error status-actions__error"
          role="alert"
        >
          <span>{mutationError}</span>
          <button type="button" onClick={onClearError}>
            Dismiss
          </button>
        </div>
      ) : null}

      <div className="status-actions__buttons" role="group" aria-label="Status actions">
        {actions.map((action) => {
          const isPending = pending === action.status && mutating;
          return (
            <button
              key={action.status}
              type="button"
              className={`status-actions__button status-actions__button--${action.variant}`}
              onClick={() => handleClick(action)}
              disabled={mutating}
              aria-label={action.description}
              title={action.description}
            >
              {isPending ? "Updating..." : action.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
