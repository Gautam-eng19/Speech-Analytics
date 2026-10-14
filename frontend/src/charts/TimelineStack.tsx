import { useEffect, useMemo, useRef } from 'react';
import type { Flaw } from '@/api/types';
import { flawsByTime, recordingDuration } from '@/lib/result';
import { clamp, FULL, panBy, span, tickLabel, timeTicks, zoomAt, type TimeWindow } from '@/lib/time';
import type { LoadedAnalysis } from '@/state/analysis';
import { hoverStore } from '@/state/ui';
import { laneHeights, laneLabel, makeCtx, type LaneKey } from './geometry';
import { FlawLane, LoudnessLane, PauseLane, PitchLane, RateLane, TruthLane, WordLane } from './lanes';
import { ActiveWord, Crosshair, FlawColumns, LiveFlaw, PlayedShade, Playhead, SelectionShade, TrimShade } from './overlays';
import { useWidth } from './useWidth';

export interface TimelineStackProps {
  analysis: LoadedAnalysis;
  /** Lanes to draw, top to bottom. The time axis is always added; the ground-truth lane follows 'flaws' when there is truth to show. */
  lanes: readonly LaneKey[];
  view: TimeWindow;
  /** When given, the stack can be zoomed (wheel) and panned (drag, Shift + wheel). */
  onView?: (view: TimeWindow) => void;
  compact?: boolean;
  heights?: Partial<Record<LaneKey, number>>;
  selected: Flaw | null;
  onSelect: (flaw: Flaw) => void;
  /** A click on empty plot area (not a drag). */
  onPlotClick?: (time: number) => void;
  showTruth: boolean;
  label: string;
}

/**
 * The shared time-aligned plot: one label column, one plot column, every lane on the same x scale. Used for the full timeline, the
 * small "at a glance" figure on the overview and the single-signal charts on the Signals page.
 */
export function TimelineStack({ analysis, lanes, view, onView, compact = false, heights, selected, onSelect, onPlotClick, showTruth, label }: TimelineStackProps) {
  const { result, sample } = analysis;
  const [plotsRef, width] = useWidth<HTMLDivElement>();
  const duration = recordingDuration(result);
  const ctx = useMemo(() => makeCtx(result, view, width), [result, view.t0, view.t1, width]);
  const flaws = useMemo(() => flawsByTime(result.flaws), [result]);
  const truth = showTruth && sample ? sample.injected : [];

  const base = laneHeights(compact);
  const heightOf = (key: LaneKey) => heights?.[key] ?? base[key];
  const ordered = useMemo(() => {
    const out: LaneKey[] = ['axis'];
    for (const key of lanes) {
      out.push(key);
      if (key === 'flaws' && truth.length > 0) out.push('truth');
    }
    return out;
  }, [lanes, truth.length]);
  const tops: Partial<Record<LaneKey, number>> = {};
  let running = 0;
  for (const key of ordered) {
    tops[key] = running;
    running += heightOf(key);
  }

  const ticks = useMemo(() => timeTicks(view, width), [view.t0, view.t1, width]);
  const tickStep = ticks.length > 1 ? ticks[1]! - ticks[0]! : 1;

  // ---- pointer interaction ---------------------------------------------------------------------------------------------------
  const viewRef = useRef(view);
  viewRef.current = view;
  const drag = useRef<{ x0: number; start: TimeWindow; moved: boolean } | null>(null);

  const timeAt = (clientX: number): number => {
    const rect = plotsRef.current?.getBoundingClientRect();
    const v = viewRef.current;
    if (!rect || rect.width === 0) return v.t0;
    return v.t0 + clamp((clientX - rect.left) / rect.width, 0, 1) * span(v);
  };

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest('[data-flaw]')) return;
    drag.current = { x0: e.clientX, start: { ...viewRef.current }, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    hoverStore.set(timeAt(e.clientX));
    const d = drag.current;
    if (!d) return;
    if (Math.abs(e.clientX - d.x0) > 3) d.moved = true;
    const rect = plotsRef.current?.getBoundingClientRect();
    if (d.moved && onView && rect && rect.width > 0) onView(panBy(d.start, -((e.clientX - d.x0) / rect.width) * span(d.start), duration));
  };
  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    drag.current = null;
    if (e.pointerType === 'touch') hoverStore.set(null);
    if (d && !d.moved) onPlotClick?.(timeAt(e.clientX));
  };

  useEffect(() => {
    const node = plotsRef.current;
    if (!node || !onView) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      const rect = node.getBoundingClientRect();
      const v = viewRef.current;
      const horizontal = e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY);
      const amount = (e.deltaMode === 1 ? 16 : 1) * (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY);
      if (horizontal) onView(panBy(v, (amount / rect.width) * span(v), duration));
      else onView(zoomAt(v, Math.exp(-amount * 0.0018), v.t0 + clamp((e.clientX - rect.left) / rect.width, 0, 1) * span(v), duration));
    };
    node.addEventListener('wheel', handler, { passive: false });
    return () => node.removeEventListener('wheel', handler);
  }, [onView, duration, plotsRef]);

  const wordsTop = tops.words;
  const zoomed = span(view) < duration - 1e-6;

  return (
    <div className="stack" role="group" aria-label={label} style={{ ['--lane-total' as string]: `${running}px` }}>
      <div className="stack__gutter">
        {ordered.map((key) => {
          const text = laneLabel(key, result);
          return (
            <div key={key} className={`glabel glabel--${key}`} style={{ height: heightOf(key) }}>
              {text.name ? <span className="glabel__name">{text.name}</span> : null}
              {text.detail && heightOf(key) >= 56 ? <span className="glabel__detail">{text.detail}</span> : null}
            </div>
          );
        })}
      </div>

      <div
        ref={plotsRef}
        className="stack__plots"
        data-pan={!!onView && zoomed}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => { drag.current = null; }}
        onPointerLeave={() => { if (!drag.current) hoverStore.set(null); }}
        onDoubleClick={() => onView?.(FULL(duration))}
      >
        <svg className="stack__grid" width={width} height={running} aria-hidden="true">
          {ticks.map((t) => <line key={t} x1={ctx.x(t)} x2={ctx.x(t)} y1={0} y2={running} />)}
        </svg>
        <TrimShade ctx={ctx} />
        <FlawColumns ctx={ctx} flaws={flaws} />
        <SelectionShade ctx={ctx} flaw={selected} />
        <PlayedShade ctx={ctx} />
        <LiveFlaw ctx={ctx} flaws={flaws} />

        {ordered.map((key) => {
          const h = heightOf(key);
          return (
            <div key={key} className={`lane lane--${key}`} style={{ height: h }}>
              {key === 'axis' ? (
                <div className="axis" aria-hidden="true">
                  {ticks.map((t) => <span key={t} className="axis__tick num" style={{ left: ctx.x(t) }}>{tickLabel(t, tickStep)}</span>)}
                </div>
              ) : null}
              {key === 'flaws' ? <FlawLane ctx={ctx} height={h} flaws={flaws} selectedId={selected?.flaw_id ?? null} onSelect={onSelect} /> : null}
              {key === 'truth' ? <TruthLane ctx={ctx} height={h} truth={truth} /> : null}
              {key === 'words' ? <WordLane ctx={ctx} height={h} /> : null}
              {key === 'loudness' ? <LoudnessLane ctx={ctx} height={h} flaws={flaws} /> : null}
              {key === 'pitch' ? <PitchLane ctx={ctx} height={h} /> : null}
              {key === 'rate' ? <RateLane ctx={ctx} height={h} flaws={flaws} /> : null}
              {key === 'pauses' ? <PauseLane ctx={ctx} height={h} flaws={flaws} /> : null}
            </div>
          );
        })}

        {wordsTop !== undefined ? <ActiveWord ctx={ctx} top={wordsTop} height={heightOf('words')} /> : null}
        <Crosshair ctx={ctx} />
        <Playhead ctx={ctx} />
      </div>
    </div>
  );
}
