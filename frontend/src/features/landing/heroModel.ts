import type { AnalysisResult, Flaw } from '@/api/types';
import { scaleLinear } from '@/lib/decimate';
import { evidenceHeadline } from '@/lib/evidence';
import { flawMeta } from '@/lib/flawMeta';
import { fmtClock, fmtNum } from '@/lib/format';
import { recordingDuration } from '@/lib/result';
import { tickLabel, timeTicks } from '@/lib/time';

/**
 * The geometry of the landing page's instrument: what is drawn where, for a given width. It is a picture of one analysis result
 * (the demo sample) and computes no measurement: the rate series, the loudness envelope, the reference corridor, the deviation
 * intervals and their evidence lines all come straight from the result, and thinning/smoothing is display only.
 * Without a result the same geometry is built from a fixed, plainly labelled illustration (see `illustrativeInput`).
 */

export interface Pt { x: number; y: number }

/** The loudness meter scale, the same fixed range the timeline's loudness lane uses. */
export const LOUDNESS_FLOOR_DB = -80;
export const LOUDNESS_CEIL_DB = 0;

export interface DeviationInput {
  id: string;
  type: string;
  start: number;
  end: number;
  /** One line of measured evidence from the result ("277 vs 167 words/min"); empty for the illustration. */
  evidence: string;
}

/** Everything the scene needs, in data space. */
export interface SceneInput {
  duration: number;
  rate: { t: number[]; wpm: number[] };
  corridor: { mean: number; std: number } | null;
  /** Peak loudness (dBFS) per equal slice of the recording; the scene resamples it to the bar count it can afford. */
  loudness: { t: number[]; db: number[] };
  deviations: DeviationInput[];
  /** An illustration has no time axis labels and no per-moment lookups. */
  illustrative: boolean;
}

export interface SceneFlag {
  id: string;
  type: string;
  label: string;
  interval: string;
  evidence: string;
  start: number;
  end: number;
  x0: number;
  x1: number;
  left: number;
  width: number;
  tier: number;
}

export interface SceneBar { x: number; h: number; hot: boolean }

export interface HeroScene {
  width: number;
  height: number;
  compact: boolean;
  duration: number;
  illustrative: boolean;
  toX: (t: number) => number;
  toTime: (x: number) => number;
  flagBand: number;
  rate: {
    top: number; bottom: number;
    toY: (wpm: number) => number;
    points: Pt[];
    line: string;
    area: string;
    mean: number | null;
    band1: [number, number] | null;
    band2: [number, number] | null;
    ticks: { y: number; label: string }[];
    /** "reference 141 ± 12 words/min": the corridor's own statistics, read from the result. */
    corridorLabel: string | null;
  };
  loud: { top: number; bottom: number; mid: number; barWidth: number; bars: SceneBar[] };
  axis: { top: number; ticks: { x: number; label: string }[] };
  flags: SceneFlag[];
}

const r2 = (v: number): number => Math.round(v * 100) / 100;

/** Height of one row of deviation labels above the tracks. */
export const tierHeight = (compact: boolean): number => (compact ? 30 : 46);
const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

/** Monotone cubic (Fritsch–Carlson) through the points as an SVG path: smooth, and never rises or falls between two samples more than the data does. */
export function monotonePath(points: readonly Pt[]): string {
  const n = points.length;
  if (n === 0) return '';
  const first = points[0] as Pt;
  if (n === 1) return `M${r2(first.x)} ${r2(first.y)}`;
  const dx: number[] = [];
  const secant: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    const a = points[i] as Pt;
    const b = points[i + 1] as Pt;
    dx.push(b.x - a.x);
    secant.push(b.x === a.x ? 0 : (b.y - a.y) / (b.x - a.x));
  }
  const tangent: number[] = new Array<number>(n).fill(0);
  tangent[0] = secant[0] as number;
  tangent[n - 1] = secant[n - 2] as number;
  for (let i = 1; i < n - 1; i++) {
    const s0 = secant[i - 1] as number;
    const s1 = secant[i] as number;
    tangent[i] = s0 * s1 <= 0 ? 0 : (s0 + s1) / 2;
  }
  for (let i = 0; i < n - 1; i++) {
    const s = secant[i] as number;
    if (s === 0) {
      tangent[i] = 0;
      tangent[i + 1] = 0;
      continue;
    }
    const a = (tangent[i] as number) / s;
    const b = (tangent[i + 1] as number) / s;
    const norm = a * a + b * b;
    if (norm > 9) {
      const k = 3 / Math.sqrt(norm);
      tangent[i] = k * a * s;
      tangent[i + 1] = k * b * s;
    }
  }
  let d = `M${r2(first.x)} ${r2(first.y)}`;
  for (let i = 0; i < n - 1; i++) {
    const a = points[i] as Pt;
    const b = points[i + 1] as Pt;
    const h = (dx[i] as number) / 3;
    d += `C${r2(a.x + h)} ${r2(a.y + (tangent[i] as number) * h)} ${r2(b.x - h)} ${r2(b.y - (tangent[i + 1] as number) * h)} ${r2(b.x)} ${r2(b.y)}`;
  }
  return d;
}

/** The loudest value in each of `count` equal time slices of [0, duration]; an empty slice reads as the meter floor. Display thinning only. */
export function peakBuckets(times: ArrayLike<number>, values: ArrayLike<number>, duration: number, count: number): number[] {
  const out = new Array<number>(Math.max(0, count)).fill(LOUDNESS_FLOOR_DB);
  const n = Math.min(times.length, values.length);
  if (count <= 0 || duration <= 0) return out;
  for (let i = 0; i < n; i++) {
    const t = times[i] as number;
    const v = values[i] as number;
    if (!Number.isFinite(t) || !Number.isFinite(v) || t < 0 || t > duration) continue;
    const bucket = Math.min(count - 1, Math.floor((t / duration) * count));
    if (v > (out[bucket] as number)) out[bucket] = v;
  }
  return out;
}

/** Place a row of labels left to right on as few tiers as possible so that none overlaps another. Deterministic. */
export function assignTiers(items: readonly { left: number; width: number }[], maxTiers: number, gap = 10): number[] {
  const rightEdge: number[] = [];
  return items.map((item) => {
    for (let tier = 0; tier < maxTiers; tier++) {
      if (rightEdge[tier] === undefined || (rightEdge[tier] as number) + gap <= item.left) {
        rightEdge[tier] = item.left + item.width;
        return tier;
      }
    }
    // No tier is free: use the one that frees up first (the label may touch its neighbour; that is better than hiding a finding).
    let best = 0;
    for (let tier = 1; tier < maxTiers; tier++) if ((rightEdge[tier] as number) < (rightEdge[best] as number)) best = tier;
    rightEdge[best] = item.left + item.width;
    return best;
  });
}

export const inputFromResult = (result: AnalysisResult): SceneInput => {
  const rate = result.features.speech_rate_timeline;
  const energy = result.features.energy_timeline;
  const stats = result.baseline_stats;
  return {
    duration: recordingDuration(result),
    rate: { t: [...rate.times_s], wpm: [...rate.words_per_min] },
    corridor: Number.isFinite(stats.rate_wpm_mean) && Number.isFinite(stats.rate_wpm_std) ? { mean: stats.rate_wpm_mean, std: stats.rate_wpm_std } : null,
    loudness: { t: [...energy.times_s], db: [...energy.values_db] },
    deviations: [...result.flaws]
      .sort((a: Flaw, b: Flaw) => a.start_s - b.start_s || a.end_s - b.end_s)
      .map((f: Flaw) => ({ id: f.flaw_id, type: f.type, start: f.start_s, end: f.end_s, evidence: evidenceHeadline(f) })),
    illustrative: false,
  };
};

/**
 * A fixed picture used only when no demo sample can be loaded. It carries no numbers and no time labels, and the page says "Illustration"
 * next to it. (Deterministic: a few sines, no randomness.)
 */
export function illustrativeInput(): SceneInput {
  const duration = 60;
  const t: number[] = [];
  const wpm: number[] = [];
  for (let i = 0; i <= 30; i++) {
    t.push(i * 2);
    const bump = Math.exp(-(((i - 20) / 2.6) ** 2));
    wpm.push(142 + 9 * Math.sin(i * 0.9) + 5 * Math.sin(i * 2.3) + 58 * bump);
  }
  const lt: number[] = [];
  const db: number[] = [];
  for (let i = 0; i < 1200; i++) {
    const time = (i / 1200) * duration;
    lt.push(time);
    const syllable = Math.abs(Math.sin(time * 5.2)) * 0.6 + Math.abs(Math.sin(time * 11.3 + 1)) * 0.4;
    const phrase = Math.sin(time * 0.62) > -0.82 ? 1 : 0.08;
    db.push(-62 + 46 * syllable * phrase);
  }
  return { duration, rate: { t, wpm }, corridor: { mean: 142, std: 12 }, loudness: { t: lt, db }, deviations: [{ id: 'illustration', type: 'illustration', start: 36, end: 44, evidence: '' }], illustrative: true };
}

/** Build the picture for a width. `compact` narrows the label band and the track heights for phones. */
export function buildScene(input: SceneInput, width: number): HeroScene {
  const compact = width < 640;
  const duration = Math.max(0.001, input.duration);
  const pad = compact ? 12 : 20;
  const toX = scaleLinear(0, duration, 0, width);
  const toTime = (x: number): number => clamp((x / Math.max(1, width)) * duration, 0, duration);

  // Flags: a label for every deviation, on as few tiers as it takes.
  const charPx = compact ? 6 : 6.5;
  const draft = input.deviations.map((d) => {
    const meta = d.type === 'illustration' ? null : flawMeta(d.type);
    const label = meta ? meta.label : 'Deviation';
    const interval = input.illustrative ? 'illustrative' : `${fmtClock(d.start, 1)}–${fmtClock(d.end, 1)}`;
    const evidence = compact ? '' : d.evidence;
    // On a narrow screen a label is just the finding's name; the interval and the evidence are in the readout and the accessible name.
    const chars = compact ? label.length : Math.max(label.length + 3 + interval.length, evidence.length);
    const w = Math.ceil(chars * charPx) + (compact ? 40 : 28);
    const x0 = toX(d.start);
    const x1 = Math.max(x0 + 3, toX(d.end));
    const left = clamp(x0 - 1, pad, Math.max(pad, width - w - pad));
    return { d, label, interval, evidence, x0, x1, left, w };
  });
  const maxTiers = compact ? 2 : 3;
  const tiers = assignTiers(draft.map((f) => ({ left: f.left, width: f.w })), maxTiers);
  const tierCount = draft.length === 0 ? 0 : Math.max(...tiers) + 1;
  const tierH = tierHeight(compact);
  const flagBand = tierCount === 0 ? 14 : 16 + tierCount * tierH;
  const flags: SceneFlag[] = draft.map((f, i) => ({
    id: f.d.id, type: f.d.type, label: f.label, interval: f.interval, evidence: f.evidence, start: f.d.start, end: f.d.end,
    x0: r2(f.x0), x1: r2(f.x1), left: r2(f.left), width: f.w, tier: tiers[i] as number,
  }));

  const rateH = compact ? 96 : 150;
  const loudH = compact ? 72 : 104;
  const rateTop = flagBand + 8;
  const rateBottom = rateTop + rateH;
  const loudTop = rateBottom + (compact ? 17 : 21);
  const loudBottom = loudTop + loudH;
  const axisTop = loudBottom + 6;
  const height = axisTop + (compact ? 24 : 28);

  // Rate: the delivery's words per minute against the reference corridor (mean ± 1 and 2 standard deviations).
  const wpm = input.rate.wpm.filter((v) => Number.isFinite(v));
  const corridor = input.corridor;
  let lo = Math.min(...(wpm.length ? wpm : [0]), corridor ? corridor.mean - 3 * corridor.std : Infinity);
  let hi = Math.max(...(wpm.length ? wpm : [1]), corridor ? corridor.mean + 3 * corridor.std : -Infinity);
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) { lo = 0; hi = 1; }
  lo = Math.max(0, Math.floor(lo / 10) * 10);
  hi = Math.ceil(hi / 10) * 10;
  const toY = scaleLinear(lo, hi, rateBottom - 6, rateTop + 6);
  const points: Pt[] = [];
  const count = Math.min(input.rate.t.length, input.rate.wpm.length);
  for (let i = 0; i < count; i++) {
    const t = input.rate.t[i] as number;
    const v = input.rate.wpm[i] as number;
    if (Number.isFinite(t) && Number.isFinite(v)) points.push({ x: r2(toX(t)), y: r2(toY(v)) });
  }
  const line = monotonePath(points);
  const lastPoint = points[points.length - 1];
  const firstPoint = points[0];
  const area = lastPoint && firstPoint ? `${line}L${lastPoint.x} ${r2(rateBottom)}L${firstPoint.x} ${r2(rateBottom)}Z` : '';
  const band = (k: number): [number, number] | null => (corridor ? [r2(toY(corridor.mean + k * corridor.std)), r2(toY(corridor.mean - k * corridor.std))] : null);
  const rateTicks = [lo, corridor ? Math.round(corridor.mean) : Math.round((lo + hi) / 2), hi].map((v) => ({ y: r2(toY(v)), label: fmtNum(v, 0) }));

  // Loudness: a mirrored envelope, one bar per few pixels, the loudest value in each slice of time.
  const pitch = compact ? 4 : 5;
  const barCount = Math.max(8, Math.floor(width / pitch));
  const peaks = peakBuckets(input.loudness.t, input.loudness.db, duration, barCount);
  const half = loudH / 2 - 3;
  const mid = loudTop + loudH / 2;
  const barWidth = Math.max(1.5, width / barCount - 1.4);
  const bars: SceneBar[] = peaks.map((db, i) => {
    const fraction = clamp((db - LOUDNESS_FLOOR_DB) / (LOUDNESS_CEIL_DB - LOUDNESS_FLOOR_DB), 0, 1);
    const centre = ((i + 0.5) / barCount) * duration;
    return { x: r2((i / barCount) * width + 0.7), h: r2(Math.max(0.8, fraction * half)), hot: input.deviations.some((d) => centre >= d.start && centre <= d.end) };
  });

  // Time axis.
  const window = { t0: 0, t1: duration };
  const ticks = timeTicks(window, width, compact ? 70 : 96);
  const step = ticks.length > 1 ? (ticks[1] as number) - (ticks[0] as number) : 1;
  const axisTicks = ticks.map((t) => ({ x: r2(toX(t)), label: input.illustrative ? '' : tickLabel(t, step) }));

  return {
    width, height, compact, duration, illustrative: input.illustrative, toX, toTime, flagBand,
    rate: {
      top: rateTop, bottom: rateBottom, toY, points, line, area, mean: corridor ? r2(toY(corridor.mean)) : null, band1: band(1), band2: band(2), ticks: rateTicks,
      corridorLabel: corridor ? (input.illustrative ? 'reference corridor' : `reference ${fmtNum(corridor.mean, 0)} ± ${fmtNum(corridor.std, 0)} words/min`) : null,
    },
    loud: { top: loudTop, bottom: loudBottom, mid: r2(mid), barWidth: r2(barWidth), bars },
    axis: { top: axisTop, ticks: axisTicks },
    flags,
  };
}
