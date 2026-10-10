import type { Flaw } from '@/api/types';
import { useWidth } from '@/charts/useWidth';
import { evidenceGauge, evidenceRows } from '@/lib/evidence';
import { flawColor } from '@/lib/flawMeta';
import { fmtNum, fmtSigned } from '@/lib/format';

/** A flaw's measured evidence as a table of rows. Values and labels come from lib/evidence.ts; the numbers are the backend's. */
export function EvidenceTable({ flaw, compact = false }: { flaw: Flaw; compact?: boolean }) {
  const rows = evidenceRows(flaw);
  return (
    <dl className={`evidence ${compact ? 'evidence--compact' : ''}`}>
      {rows.map((row) => (
        <div key={row.label} className="evidence__row">
          <dt>{row.label}</dt>
          <dd>
            <span className="num evidence__value">{row.value}</span>
            {row.unit ? <span className="evidence__unit">{row.unit}</span> : null}
            {row.hint && !compact ? <span className="evidence__hint">{row.hint}</span> : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Where the participant's value sits against the baseline: the baseline's mean and its one- and two-standard-deviation spread are
 * drawn on a linear axis in the measurement's own unit, the participant value is the marker, and the detection rule's threshold is
 * the dashed line. The axis stretches to include the value, so an extreme outlier looks like one.
 */
export function EvidenceGauge({ flaw }: { flaw: Flaw }) {
  const gauge = evidenceGauge(flaw);
  const [ref, width] = useWidth<HTMLDivElement>();
  if (!gauge) return null;
  const { value, mean, std, unit, decimals } = gauge;
  const threshold = flaw.rule ? mean + flaw.rule.threshold_z * std : null;
  const lo = Math.min(value, mean - 3 * std, threshold ?? Infinity);
  const hi = Math.max(value, mean + 3 * std, threshold ?? -Infinity);
  const pad = (hi - lo) * 0.06;
  const w = Math.max(240, width);
  const left = 14;
  const right = w - 14;
  const x = (v: number) => left + ((v - (lo - pad)) / (hi - lo + 2 * pad)) * (right - left);
  const color = flawColor(flaw.type);
  const markerX = x(value);
  const flip = markerX > w - 120;
  const cap = (n: number) => Math.max(left, Math.min(right, n));
  const anchorFor = (px: number) => (px < left + 60 ? 'start' : px > right - 60 ? 'end' : 'middle');

  return (
    <div className="gauge" ref={ref} style={{ ['--c' as string]: color }}>
      <svg width={w} height={118} role="img" aria-label={`${gauge.label}: participant ${fmtNum(value, decimals)} ${unit}, baseline mean ${fmtNum(mean, decimals)} ${unit}, z-score ${fmtSigned(gauge.z, 2)}`}>
        <line className="gauge__axis" x1={left} x2={right} y1={62} y2={62} />
        <rect className="gauge__band2" x={cap(x(mean - 2 * std))} width={Math.max(0, cap(x(mean + 2 * std)) - cap(x(mean - 2 * std)))} y={52} height={20} rx={2} />
        <rect className="gauge__band1" x={cap(x(mean - std))} width={Math.max(0, cap(x(mean + std)) - cap(x(mean - std)))} y={52} height={20} rx={2} />
        <line className="gauge__mean" x1={x(mean)} x2={x(mean)} y1={46} y2={78} />
        <text className="gauge__label gauge__label--base" x={x(mean)} y={96} textAnchor={anchorFor(x(mean))}>baseline {fmtNum(mean, decimals)}</text>
        {threshold !== null ? (
          <g>
            <line className="gauge__threshold" x1={x(threshold)} x2={x(threshold)} y1={46} y2={80} />
            <text className="gauge__label gauge__label--thr" x={x(threshold)} y={111} textAnchor={anchorFor(x(threshold))}>rule flags at {fmtNum(threshold, decimals)}</text>
          </g>
        ) : null}
        <g className="gauge__marker">
          <line x1={markerX} x2={markerX} y1={26} y2={62} />
          <path d={`M${markerX - 6} 62 L${markerX + 6} 62 L${markerX} 52 Z`} />
          <text x={markerX + (flip ? -8 : 8)} y={20} textAnchor={flip ? 'end' : 'start'} className="gauge__value num">{fmtNum(value, decimals)} {unit}</text>
          <text x={markerX + (flip ? -8 : 8)} y={34} textAnchor={flip ? 'end' : 'start'} className="gauge__z num">z {fmtSigned(gauge.z, 2)}</text>
        </g>
      </svg>
      <div className="gauge__legend">
        <span><i className="swatch swatch--band1" /> mean ± 1 SD</span>
        <span><i className="swatch swatch--band2" /> ± 2 SD</span>
        {threshold !== null ? <span><i className="swatch swatch--threshold" /> where the rule flags</span> : null}
        <span><i className="swatch swatch--marker" /> this finding</span>
      </div>
    </div>
  );
}
