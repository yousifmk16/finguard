const DATE_TIME_FMT = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return "-";
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "-";
  return DATE_TIME_FMT.format(date);
}

export function formatScore(value: number | null | undefined, fractionDigits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toFixed(fractionDigits);
}

export function shortId(value: string, head = 8): string {
  if (!value) return "-";
  return value.length <= head ? value : `${value.slice(0, head)}...`;
}
