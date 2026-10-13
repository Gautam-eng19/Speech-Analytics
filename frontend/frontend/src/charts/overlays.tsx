import type { Flaw } from '@/api/types';
import { flawColor } from '@/lib/flawMeta';
import { analysedSpan, wordIndexAt } from '@/lib/result';
import { useTimecode } from '@/lib/settings';
import { useStore } from '@/lib/store';
import { playerStore, usePlayhead } from '@/state/player';
import { hoverStore } from '@/state/ui';
import type { LaneCtx } from './geometry';

/** Things drawn over the lanes. They subscribe to the playhead and the pointer themselves, so the lanes do not re-render at 60 Hz. */

const cssVar = (name: string, value: string) => ({ [name]: value }) as React.CSSProperties;

export function Playhead({ ctx }: { ctx: LaneCtx }) {
  const t = usePlayhead();
  const hasAudio = useStore(playerStore, (s) => s.src !== null);
  const tc = useTimecode();
  if ((!hasAudio && t === 0) || t < ctx.t0 || t > ctx.t1) return null;
  const x = ctx.x(t);
  // Keep the time flag inside the plot: left-aligned near the start, right-aligned near the end.
  const shift = x < 30 ? 0 : x > ctx.width - 30 ? -100 : -50;
  return (
    <div className="ov ov--playhead" style={{ transform: `translateX(${x.toFixed(1)}px)` }} aria-hidden="true">
      <span className="ov__flag num" style={{ transform: `translateX(${shift}%)` }}>{tc.at(t)}</span>
    </div>
  );
}

export function Crosshair({ ctx }: { ctx: LaneCtx }) {
  const t = useStore(hoverStore, (h) => h);
  const tc = useTimecode();
  if (t === null || t < ctx.t0 || t > ctx.t1) return null;
  return (
    <div className="ov ov--cross" style={{ transform: `translateX(${ctx.x(t).toFixed(1)}px)` }} aria-hidden="true">
      <span className="ov__tag num">{tc.at(t, 2)}</span>
    </div>
  );
}

/** Every finding as a faint column through all lanes, so one event can be followed from lane to lane. */
export function FlawColumns({ ctx, flaws }: { ctx: LaneCtx; flaws: readonly Flaw[] }) {
  return (
    <>
      {flaws.map((f) => {
        const left = ctx.x(f.start_s);
        const width = Math.max(2, ctx.x(f.end_s) - left);
        if (left + width < 0 || left > ctx.width) return null;
        return <div key={f.flaw_id} className="ov ov--column" style={{ left, width, ...cssVar('--c', flawColor(f.type)) }} aria-hidden="true" />;
      })}
    </>
  );
}

export function SelectionShade({ ctx, flaw }: { ctx: LaneCtx; flaw: Flaw | null }) {
  if (!flaw) return null;
  const left = ctx.x(flaw.start_s);
  const width = Math.max(2, ctx.x(flaw.end_s) - left);
  if (left + width < 0 || left > ctx.width) return null;
  return <div className="ov ov--selection" style={{ left, width, ...cssVar('--c', flawColor(flaw.type)) }} aria-hidden="true" />;
}

/** Hatching over the leading and trailing silence that the pipeline trimmed before analysis. */
export function TrimShade({ ctx }: { ctx: LaneCtx }) {
  const { start, end } = analysedSpan(ctx.result);
  const leftEdge = ctx.x(start);
  const rightEdge = ctx.x(end);
  return (
    <>
      {start > ctx.t0 ? <div className="ov ov--trim" style={{ left: 0, width: Math.min(ctx.width, Math.max(0, leftEdge)) }} aria-hidden="true" /> : null}
      {end < ctx.t1 ? <div className="ov ov--trim" style={{ left: Math.max(0, rightEdge), right: 0 }} aria-hidden="true" /> : null}
    </>
  );
}

/** The word being spoken, outlined in the word lane while playing or after a seek. */
export function ActiveWord({ ctx, top, height }: { ctx: LaneCtx; top: number; height: number }) {
  const t = usePlayhead();
  const hasAudio = useStore(playerStore, (s) => s.src !== null);
  if (!hasAudio) return null;
  const words = ctx.result.alignment;
  const i = wordIndexAt(words, t);
  const word = words[i];
  if (!word || t > word.end_s + 0.12) return null;
  const left = ctx.x(word.start_s);
  const width = Math.max(2, ctx.x(word.end_s) - left);
  if (left + width < 0 || left > ctx.width) return null;
  return <div className="ov ov--word" style={{ left, width, top, height }} aria-hidden="true" />;
}
