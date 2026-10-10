/**
 * Display-only thinning of long timelines so a chart draws at most ~2 points per pixel column.
 * Nothing here changes what the data says: the minimum and maximum of every bucket are kept (or, in 'peak' mode, the maximum), so peaks never disappear.
 */
export interface Point {
  t: number;
  v: number;
}

/** Points of a continuous series inside [t0, t1] (plus one neighbour on each side so lines reach the edges), thinned to the width. */
export function envelope(times: ArrayLike<number>, values: ArrayLike<number>, t0: number, t1: number, widthPx: number, mode: 'minmax' | 'peak' = 'minmax'): Point[] {
  const n = Math.min(times.length, values.length);
  if (n === 0 || t1 <= t0) return [];
  let lo = lowerBound(times, t0, n);
  let hi = lowerBound(times, t1, n);
  lo = Math.max(0, lo - 1);
  hi = Math.min(n - 1, hi);
  const count = hi - lo + 1;
  const buckets = Math.max(1, Math.floor(widthPx));
  if (count <= buckets * 2) {
    const out: Point[] = [];
    for (let i = lo; i <= hi; i++) out.push({ t: times[i] as number, v: values[i] as number });
    return out;
  }
  const out: Point[] = [];
  const per = count / buckets;
  for (let b = 0; b < buckets; b++) {
    const start = lo + Math.floor(b * per);
    const end = Math.min(hi, lo + Math.floor((b + 1) * per) - 1);
    if (end < start) continue;
    let minI = start;
    let maxI = start;
    for (let i = start; i <= end; i++) {
      if ((values[i] as number) < (values[minI] as number)) minI = i;
      if ((values[i] as number) > (values[maxI] as number)) maxI = i;
    }
    if (mode === 'peak') {
      out.push({ t: times[maxI] as number, v: values[maxI] as number });
      continue;
    }
    const first = Math.min(minI, maxI);
    const second = Math.max(minI, maxI);
    out.push({ t: times[first] as number, v: values[first] as number });
    if (second !== first) out.push({ t: times[second] as number, v: values[second] as number });
  }
  return out;
}

export interface Run {
  points: Point[];
}

/** Consecutive voiced (non-null) samples as separate runs, so unvoiced gaps are real gaps in the line. */
export function voicedRuns(times: ArrayLike<number>, values: ArrayLike<number | null>, t0: number, t1: number, widthPx: number): Run[] {
  const n = Math.min(times.length, values.length);
  const runs: Run[] = [];
  let current: Point[] = [];
  const lo = Math.max(0, lowerBound(times, t0, n) - 1);
  const hi = Math.min(n - 1, lowerBound(times, t1, n));
  for (let i = lo; i <= hi; i++) {
    const v = values[i];
    if (v === null || v === undefined) {
      if (current.length) runs.push({ points: current });
      current = [];
    } else current.push({ t: times[i] as number, v });
  }
  if (current.length) runs.push({ points: current });
  const total = runs.reduce((sum, r) => sum + r.points.length, 0);
  if (total <= widthPx * 2) return runs;
  const keep = Math.ceil(total / (widthPx * 2));
  return runs.map((r) => ({ points: r.points.filter((_, i) => i % keep === 0 || i === r.points.length - 1) }));
}

function lowerBound(sorted: ArrayLike<number>, x: number, n = sorted.length): number {
  let lo = 0;
  let hi = n;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((sorted[mid] as number) < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export function extent(values: ArrayLike<number | null>, from = 0, to = values.length): [number, number] | null {
  let min = Infinity;
  let max = -Infinity;
  for (let i = from; i < to; i++) {
    const v = values[i];
    if (v === null || v === undefined || !Number.isFinite(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return min <= max ? [min, max] : null;
}

/** Linear scale from a domain to a range. */
export function scaleLinear(d0: number, d1: number, r0: number, r1: number): (x: number) => number {
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  return (x) => r0 + (x - d0) * k;
}

export function linePath(points: Point[], x: (t: number) => number, y: (v: number) => number): string {
  if (points.length === 0) return '';
  let d = `M${x(points[0]!.t).toFixed(1)} ${y(points[0]!.v).toFixed(1)}`;
  for (let i = 1; i < points.length; i++) d += `L${x(points[i]!.t).toFixed(1)} ${y(points[i]!.v).toFixed(1)}`;
  return d;
}

/** Step ("hold") path: the value stays until the next sample. Used for windowed measurements such as speech rate. */
export function stepPath(points: Point[], x: (t: number) => number, y: (v: number) => number): string {
  if (points.length === 0) return '';
  let d = `M${x(points[0]!.t).toFixed(1)} ${y(points[0]!.v).toFixed(1)}`;
  for (let i = 1; i < points.length; i++) {
    const p = points[i]!;
    d += `H${x(p.t).toFixed(1)}V${y(p.v).toFixed(1)}`;
  }
  return d;
}

/** Closed area under a line down to `yBase` (used for the loudness trace). */
export function areaPath(points: Point[], x: (t: number) => number, y: (v: number) => number, yBase: number): string {
  if (points.length === 0) return '';
  const first = points[0]!;
  const last = points[points.length - 1]!;
  return `${linePath(points, x, y)}L${x(last.t).toFixed(1)} ${yBase.toFixed(1)}L${x(first.t).toFixed(1)} ${yBase.toFixed(1)}Z`;
}

/** Round axis ticks (1, 2, 5 x 10^k) inside [lo, hi], about `target` of them. */
export function niceTicks(lo: number, hi: number, target = 4): number[] {
  const width = hi - lo;
  if (!(width > 0) || !Number.isFinite(width)) return [];
  const raw = width / Math.max(1, target);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / magnitude;
  const step = (norm < 1.5 ? 1 : norm < 3.5 ? 2 : norm < 7.5 ? 5 : 10) * magnitude;
  const ticks: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) ticks.push(Number((Math.round(v / step) * step).toFixed(6)));
  return ticks;
}
