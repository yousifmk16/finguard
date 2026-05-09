import type { TrendPoint } from "./types";

interface Props {
  points: TrendPoint[];
  width?: number;
  height?: number;
  ariaLabel: string;
  /** Highlight the highest point as an anomaly marker */
  showPeak?: boolean;
}

const PAD = 4;

export default function Sparkline({
  points,
  width = 320,
  height = 72,
  ariaLabel,
  showPeak = false,
}: Props) {
  if (points.length === 0) {
    return (
      <div className="sparkline sparkline--empty" role="img" aria-label={`${ariaLabel}: no data`}>
        <span aria-hidden="true">No data</span>
      </div>
    );
  }

  const max    = Math.max(...points.map((p) => p.count), 1);
  const innerW = width - PAD * 2;
  const innerH = height - PAD * 2;
  const stepX  = points.length > 1 ? innerW / (points.length - 1) : 0;

  const coords = points.map((p, i) => ({
    x: PAD + i * stepX,
    y: PAD + innerH - (p.count / max) * innerH,
    count: p.count,
  }));

  const linePoints = coords.map((c) => `${c.x.toFixed(2)},${c.y.toFixed(2)}`).join(" ");

  const areaPath =
    coords.length > 1
      ? `M ${coords[0].x.toFixed(2)},${PAD + innerH} ` +
        coords.map((c) => `L ${c.x.toFixed(2)},${c.y.toFixed(2)}`).join(" ") +
        ` L ${coords[coords.length - 1].x.toFixed(2)},${PAD + innerH} Z`
      : "";

  const last = coords[coords.length - 1];

  const peakIdx = coords.reduce(
    (best, c, i) => (c.count > coords[best].count ? i : best),
    0,
  );
  const peak = coords[peakIdx];

  const gradId = `sg-${ariaLabel.replace(/\W/g, "")}`;

  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      role="img"
      aria-label={ariaLabel}
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor="var(--accent)" stopOpacity="0.25" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.02" />
        </linearGradient>
      </defs>

      {areaPath ? <path className="sparkline__area" d={areaPath} fill={`url(#${gradId})`} /> : null}
      <polyline className="sparkline__line" points={linePoints} fill="none" />

      {/* Peak anomaly marker */}
      {showPeak && peakIdx > 0 ? (
        <circle cx={peak.x} cy={peak.y} r={5} fill="var(--c-high)" stroke="var(--surface)" strokeWidth={2} />
      ) : null}

      {/* Last-value dot */}
      <circle className="sparkline__dot" cx={last.x} cy={last.y} r={3} />
    </svg>
  );
}
