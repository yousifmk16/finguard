import type { TrendPoint } from "./types";

interface Props {
  points: TrendPoint[];
  width?: number;
  height?: number;
  ariaLabel: string;
}

const PADDING = 4;

export default function Sparkline({
  points,
  width = 320,
  height = 64,
  ariaLabel,
}: Props) {
  if (points.length === 0) {
    return (
      <div
        className="sparkline sparkline--empty"
        role="img"
        aria-label={`${ariaLabel}: no data`}
      >
        <span aria-hidden="true">No data</span>
      </div>
    );
  }

  const max = Math.max(...points.map((p) => p.count), 1);
  const innerW = width - PADDING * 2;
  const innerH = height - PADDING * 2;
  const stepX = points.length > 1 ? innerW / (points.length - 1) : 0;

  // Build the polyline + filled area beneath it.
  const linePoints = points
    .map((p, i) => {
      const x = PADDING + i * stepX;
      const y = PADDING + innerH - (p.count / max) * innerH;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  const areaPath =
    points.length > 1
      ? `M ${PADDING},${PADDING + innerH} L ${linePoints
          .split(" ")
          .join(" L ")} L ${(PADDING + innerW).toFixed(2)},${PADDING + innerH} Z`
      : "";

  const last = points[points.length - 1];
  const lastX = PADDING + (points.length - 1) * stepX;
  const lastY = PADDING + innerH - (last.count / max) * innerH;

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
      {areaPath ? <path className="sparkline__area" d={areaPath} /> : null}
      <polyline className="sparkline__line" points={linePoints} fill="none" />
      <circle className="sparkline__dot" cx={lastX} cy={lastY} r={3} />
    </svg>
  );
}
