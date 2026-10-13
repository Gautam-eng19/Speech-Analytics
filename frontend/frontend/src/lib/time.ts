/** Time-window math for the timeline. Pure functions; no analysis. */

export interface TimeWindow {
  t0: number;
  t1: number;
}

export const clamp = (value: number, min: number, max: number): number => Math.min(max, Math.max(min, value));

export function span(w: TimeWindow): number {
  return w.t1 - w.t0;
}

/** Smallest visible span: a tenth of a second, or the whole recording if it is shorter. */
export function minSpan(duration: number): number {
  return Math.min(0.5, duration);
}

/** Keep a window inside [0, duration] without changing its span (unless it is longer than the recording). */
export function clampWindow(w: TimeWindow, duration: number): TimeWindow {
  const width = Math.min(span(w), duration);
  const t0 = clamp(w.t0, 0, Math.max(0, duration - width));
  return { t0, t1: t0 + width };
}

/** Zoom by `factor` (> 1 zooms in) keeping the time under `anchor` where it is on screen. */
export function zoomAt(w: TimeWindow, factor: number, anchor: number, duration: number): TimeWindow {
  const width = clamp(span(w) / factor, minSpan(duration), duration);
  const ratio = span(w) > 0 ? (anchor - w.t0) / span(w) : 0.5;
  return clampWindow({ t0: anchor - ratio * width, t1: anchor - ratio * width + width }, duration);
}

export function panBy(w: TimeWindow, delta: number, duration: number): TimeWindow {
  return clampWindow({ t0: w.t0 + delta, t1: w.t1 + delta }, duration);
}

/** A window that shows [start, end] with some context around it. */
export function windowAround(start: number, end: number, duration: number, padFraction = 0.35): TimeWindow {
  const length = Math.max(end - start, minSpan(duration));
  const pad = length * padFraction;
  return clampWindow({ t0: start - pad, t1: end + pad }, duration);
}

export const FULL = (duration: number): TimeWindow => ({ t0: 0, t1: duration });

/** Round, human-friendly tick positions for a time axis so that labels are at least `minPx` apart. */
export function timeTicks(w: TimeWindow, widthPx: number, minPx = 84): number[] {
  const width = span(w);
  if (width <= 0 || widthPx <= 0) return [];
  const steps = [0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const wanted = (width / widthPx) * minPx;
  const step = steps.find((s) => s >= wanted) ?? steps[steps.length - 1]!;
  const first = Math.ceil(w.t0 / step) * step;
  const ticks: number[] = [];
  for (let t = first; t <= w.t1 + 1e-9; t += step) ticks.push(Math.round(t * 1000) / 1000);
  return ticks;
}

export function tickLabel(t: number, step: number): string {
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  if (step >= 1) return m > 0 ? `${m}:${String(Math.round(s)).padStart(2, '0')}` : `${Math.round(s)}s`;
  const digits = step < 0.1 ? 2 : 1;
  return m > 0 ? `${m}:${s.toFixed(digits).padStart(3 + digits, '0')}` : `${s.toFixed(digits)}s`;
}

/** Index of the last element of a sorted array that is <= x (or -1). */
export function floorIndex(sorted: ArrayLike<number>, x: number): number {
  let lo = 0;
  let hi = sorted.length - 1;
  let answer = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if ((sorted[mid] as number) <= x) {
      answer = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return answer;
}

/** Index of the element of a sorted array nearest to x (or -1 for an empty array). */
export function nearestIndex(sorted: ArrayLike<number>, x: number): number {
  if (sorted.length === 0) return -1;
  const i = floorIndex(sorted, x);
  if (i < 0) return 0;
  if (i >= sorted.length - 1) return sorted.length - 1;
  return x - (sorted[i] as number) <= (sorted[i + 1] as number) - x ? i : i + 1;
}
