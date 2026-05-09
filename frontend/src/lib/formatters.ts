const DATE_TIME_FMT = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

const MONEY_FMT = new Intl.NumberFormat(undefined, {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return "-";
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "-";
  return DATE_TIME_FMT.format(date);
}

export function formatScore(value: number | null | undefined, fractionDigits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const digits = Math.max(0, Math.min(100, Math.trunc(fractionDigits)));
  return value.toFixed(digits);
}

export function shortId(value: string, head = 8): string {
  if (!value) return "-";
  return value.length <= head ? value : `${value.slice(0, head)}…`;
}

export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return MONEY_FMT.format(value);
}

export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(0)}%`;
}

export function formatRelTime(value: string | number | Date | null | undefined, now?: number): string {
  if (!value) return "-";
  const ts = typeof value === "number" ? value : new Date(value).getTime();
  if (Number.isNaN(ts)) return "-";
  const diffMs = (now ?? Date.now()) - ts;
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.round(diffH / 24);
  if (diffD < 30) return `${diffD}d ago`;
  const diffMo = Math.round(diffD / 30);
  return `${diffMo}mo ago`;
}
