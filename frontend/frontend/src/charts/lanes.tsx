import { memo, useMemo } from 'react';
import type { Flaw, SampleInjected } from '@/api/types';
import { Icon } from '@/components/Icon';
import { areaPath, envelope, linePath, voicedRuns } from '@/lib/decimate';
import { flawColor, flawMeta } from '@/lib/flawMeta';
import { fmtNum } from '@/lib/format';
import { dimensionOf, wordIndexAt } from '@/lib/result';
import { LANE_PAD, LOUDNESS_MODEL, pitchModel, rateModel, yScale, type LaneCtx, type YModel } from './geometry';

interface LaneProps {
  ctx: LaneCtx;
  height: number;
}

const cssVar = (name: string, value: string) => ({ [name]: value }) as React.CSSProperties;

/** Light horizontal rules at the y-axis ticks. */
function YGrid({ model, y, width }: { model: YModel; y: (v: number) => number; width: number }) {
  // Keep a tick only if it is at least 22 px from the last one drawn and not so close to the top that its label would be cut off.
  const shown: number[] = [];
  for (const tick of [...model.ticks].sort((a, b) => y(a) - y(b))) {
    const py = y(tick);
    if (py < 12) continue;
    const last = shown[shown.length - 1];
    if (last === undefined || py - y(last) >= 22) shown.push(tick);
  }
  return (
    <g className="lane-grid">
      {shown.map((tick) => (
        <g key={tick}>
          <line x1={0} x2={width} y1={y(tick)} y2={y(tick)} />
          <text className="ytick" x={6} y={y(tick) - 3}>{fmtNum(tick, model.decimals)}</text>
        </g>
      ))}
    </g>
  );
}

/** Baseline mean with its one- and two-standard-deviation bands (display of the baseline's own statistics). */
function BaselineBands({ mean, std, y, width }: { mean: number; std: number; y: (v: number) => number; width: number }) {
  return (
    <g className="lane-baseline">
      <rect className="band band--2" x={0} width={width} y={y(mean + 2 * std)} height={Math.max(0, y(mean - 2 * std) - y(mean + 2 * std))} />
      <rect className="band band--1" x={0} width={width} y={y(mean + std)} height={Math.max(0, y(mean - std) - y(mean + std))} />
      <line className="mean-line" x1={0} x2={width} y1={y(mean)} y2={y(mean)} />
    </g>
  );
}

/** Flaws of one score dimension, drawn in the lane they belong to. */
function FlawMarks({ ctx, height, dimension, flaws }: { ctx: LaneCtx; height: number; dimension: string; flaws: readonly Flaw[] }) {
  return (
    <g>
      {flaws.filter((f) => dimensionOf(f.type) === dimension).map((f) => {
        const left = ctx.x(f.start_s);
        const width = Math.max(2, ctx.x(f.end_s) - left);
        if (left + width < 0 || left > ctx.width) return null;
        return (
          <g key={f.flaw_id} style={cssVar('--c', flawColor(f.type))}>
            <rect className="lane-flaw" x={left} y={0} width={width} height={height} />
            <rect className="lane-flaw-cap" x={left} y={0} width={width} height={3} />
          </g>
        );
      })}
    </g>
  );
}

// ---- loudness ------------------------------------------------------------------------------------------------------------
export const LoudnessLane = memo(function LoudnessLane({ ctx, height, flaws }: LaneProps & { flaws: readonly Flaw[] }) {
  const { result, t0, t1, width, x } = ctx;
  const bs = result.baseline_stats;
  const [lo, hi] = LOUDNESS_MODEL.domain;
  const y = yScale(LOUDNESS_MODEL, height);
  const timeline = result.features.energy_timeline;
  const points = useMemo(
    () => envelope(timeline.times_s, timeline.values_db, t0, t1, width, 'peak').map((p) => ({ t: p.t, v: Math.min(hi, Math.max(lo, p.v)) })),
    [timeline, t0, t1, width, lo, hi],
  );
  return (
    <svg className="lane-svg" width={width} height={height} role="img" aria-label="Loudness over time in dBFS, against the baseline band">
      <YGrid model={LOUDNESS_MODEL} y={y} width={width} />
      <FlawMarks ctx={ctx} height={height} dimension="energy" flaws={flaws} />
      <BaselineBands mean={bs.energy_db_mean} std={bs.energy_db_std} y={y} width={width} />
      <path className="trace-area" d={areaPath(points, x, y, y(lo))} />
      <path className="trace" d={linePath(points, x, y)} />
    </svg>
  );
});

// ---- pitch ---------------------------------------------------------------------------------------------------------------
export const PitchLane = memo(function PitchLane({ ctx, height }: LaneProps) {
  const { result, t0, t1, width, x } = ctx;
  const bs = result.baseline_stats;
  const model = useMemo(() => pitchModel(result), [result]);
  const timeline = result.features.f0_timeline;
  const { lines, dots } = useMemo(() => {
    if (!model) return { lines: '', dots: '' };
    const y = yScale(model, height);
    const runs = voicedRuns(timeline.times_s, timeline.values_hz, t0, t1, width);
    return {
      lines: runs.filter((run) => run.points.length > 1).map((run) => linePath(run.points, x, y)).join(''),
      // One zero-length segment per estimate; the round line cap turns each into a dot (one element instead of thousands).
      dots: runs.flatMap((run) => run.points).map((p) => `M${x(p.t).toFixed(1)} ${y(p.v).toFixed(1)}h0`).join(''),
    };
  }, [model, timeline, t0, t1, width, height, x]);
  if (!model) return <svg className="lane-svg" width={width} height={height} />;
  const y = yScale(model, height);
  const p05 = bs.f0_voiced_hz_p05 ?? bs.f0_voiced_hz_mean - bs.f0_voiced_hz_std;
  const p95 = bs.f0_voiced_hz_p95 ?? bs.f0_voiced_hz_mean + bs.f0_voiced_hz_std;
  return (
    <svg className="lane-svg" width={width} height={height} role="img" aria-label="Pitch (F0) of the voiced speech over time, against the baseline range">
      <YGrid model={model} y={y} width={width} />
      <rect className="band band--1" x={0} width={width} y={y(p95)} height={Math.max(0, y(p05) - y(p95))} />
      <line className="mean-line" x1={0} x2={width} y1={y(bs.f0_voiced_hz_mean)} y2={y(bs.f0_voiced_hz_mean)} />
      <path className="trace trace--pitch" d={lines} />
      <path className="trace-dots" d={dots} />
    </svg>
  );
});

// ---- speech rate ---------------------------------------------------------------------------------------------------------
export const RateLane = memo(function RateLane({ ctx, height, flaws }: LaneProps & { flaws: readonly Flaw[] }) {
  const { result, width, x } = ctx;
  const bs = result.baseline_stats;
  const model = useMemo(() => rateModel(result), [result]);
  const timeline = result.features.speech_rate_timeline;
  if (!model) return <svg className="lane-svg" width={width} height={height} />;
  const y = yScale(model, height);
  const points = timeline.times_s.map((t, i) => ({ t, v: timeline.words_per_min[i] ?? 0 }));
  const rateFlaws = flaws.filter((f) => dimensionOf(f.type) === 'speech_rate');
  return (
    <svg className="lane-svg" width={width} height={height} role="img" aria-label="Speech rate per window in words per minute, against the baseline band">
      <YGrid model={model} y={y} width={width} />
      <FlawMarks ctx={ctx} height={height} dimension="speech_rate" flaws={flaws} />
      <BaselineBands mean={bs.rate_wpm_mean} std={bs.rate_wpm_std} y={y} width={width} />
      <path className="trace" d={linePath(points, x, y)} />
      {points.map((p, i) => {
        const cx = x(p.t);
        if (cx < -6 || cx > width + 6) return null;
        const hit = rateFlaws.find((f) => p.t >= f.start_s && p.t <= f.end_s);
        return (
          <circle
            key={i}
            className={hit ? 'dot dot--flag' : 'dot'}
            cx={cx}
            cy={y(p.v)}
            r={hit ? 4 : 3.2}
            style={hit ? cssVar('--c', flawColor(hit.type)) : undefined}
          >
            <title>{`${fmtNum(p.v, 1)} words/min, window around ${fmtNum(p.t, 1)} s`}</title>
          </circle>
        );
      })}
    </svg>
  );
});

// ---- pauses --------------------------------------------------------------------------------------------------------------
export const PauseLane = memo(function PauseLane({ ctx, height, flaws }: LaneProps & { flaws: readonly Flaw[] }) {
  const { result, width, x } = ctx;
  const events = result.features.pause_events;
  const longest = Math.max(0.5, ...events.map((e) => e.duration_s));
  const inner = height - 2 * LANE_PAD;
  const pauseFlaws = flaws.filter((f) => f.type === 'excessive_pause');
  return (
    <svg className="lane-svg" width={width} height={height} role="img" aria-label="Pauses between words; taller bars are longer pauses">
      <line className="lane-base" x1={0} x2={width} y1={height - LANE_PAD} y2={height - LANE_PAD} />
      {events.map((e, i) => {
        const left = x(e.start_s);
        const w = Math.max(2, x(e.end_s) - left);
        if (left + w < 0 || left > width) return null;
        const h = Math.max(5, (e.duration_s / longest) * inner * 0.8);
        const flagged = pauseFlaws.find((f) => f.start_s <= e.end_s + 0.02 && f.end_s >= e.start_s - 0.02);
        return (
          <g key={i} style={flagged ? cssVar('--c', flawColor(flagged.type)) : undefined}>
            <rect
              className={`pause pause--${e.boundary_type} ${flagged ? 'pause--flag' : ''}`}
              x={left}
              y={height - LANE_PAD - h}
              width={w}
              height={h}
              rx={1.5}
            >
              <title>{`${fmtNum(e.duration_s, 2)} s pause (${e.boundary_type.replace('_', ' ')}) at ${fmtNum(e.start_s, 2)} s`}</title>
            </rect>
            {w >= 30 ? <text className="pause-label" x={left + w / 2} y={height - LANE_PAD - h - 3} textAnchor="middle">{fmtNum(e.duration_s, 2)}</text> : null}
          </g>
        );
      })}
    </svg>
  );
});

// ---- words ---------------------------------------------------------------------------------------------------------------
export const WordLane = memo(function WordLane({ ctx, height }: LaneProps) {
  const { result, t0, t1, x } = ctx;
  const words = result.alignment;
  const first = Math.max(0, wordIndexAt(words, t0));
  const items: React.ReactNode[] = [];
  for (let i = first; i < words.length; i++) {
    const w = words[i]!;
    if (w.start_s > t1) break;
    if (w.end_s < t0) continue;
    const left = x(w.start_s);
    const width = Math.max(1, x(w.end_s) - left - 1);
    const readable = width >= 26;
    items.push(
      <div
        key={i}
        className={`word ${readable ? '' : 'word--tick'}`}
        style={{ left, width, ['--low' as string]: String(1 - Math.min(1, Math.max(0, w.confidence))) }}
        title={`${w.word}  ·  ${fmtNum(w.start_s, 2)}–${fmtNum(w.end_s, 2)} s  ·  confidence ${fmtNum(w.confidence, 2)}`}
      >
        {readable ? w.word : null}
      </div>,
    );
  }
  return <div className="lane-words" style={{ height }}>{items}</div>;
});

// ---- findings ------------------------------------------------------------------------------------------------------------
export const FlawLane = memo(function FlawLane({
  ctx, height, flaws, selectedId, onSelect,
}: LaneProps & { flaws: readonly Flaw[]; selectedId: string | null; onSelect: (flaw: Flaw) => void }) {
  return (
    <div className="lane-flaws" style={{ height }}>
      {flaws.map((f) => {
        const left = ctx.x(f.start_s);
        const width = Math.max(6, ctx.x(f.end_s) - left);
        if (left + width < 0 || left > ctx.width) return null;
        const meta = flawMeta(f.type);
        const selected = f.flaw_id === selectedId;
        return (
          <button
            key={f.flaw_id}
            type="button"
            data-flaw={f.flaw_id}
            className={`flawband ${selected ? 'is-selected' : ''}`}
            style={{ left, width, ...cssVar('--c', flawColor(f.type)) }}
            aria-pressed={selected}
            aria-label={`${meta.label}, ${fmtNum(f.start_s, 1)} to ${fmtNum(f.end_s, 1)} seconds, severity ${fmtNum(f.severity, 2)}`}
            title={`${meta.label}  ·  ${fmtNum(f.start_s, 1)}–${fmtNum(f.end_s, 1)} s  ·  severity ${fmtNum(f.severity, 2)}`}
            onClick={(e) => { e.stopPropagation(); onSelect(f); }}
          >
            {width >= 22 ? <Icon name={meta.icon} size={13} /> : null}
            {width >= 104 ? <span className="flawband__label">{meta.label}</span> : null}
          </button>
        );
      })}
    </div>
  );
});

// ---- ground truth (demo samples) -----------------------------------------------------------------------------------------
export const TruthLane = memo(function TruthLane({ ctx, height, truth }: LaneProps & { truth: readonly SampleInjected[] }) {
  return (
    <div className="lane-truth" style={{ height }}>
      {truth.map((t, i) => {
        const left = ctx.x(t.start_s);
        const width = Math.max(4, ctx.x(t.end_s) - left);
        if (left + width < 0 || left > ctx.width) return null;
        const meta = flawMeta(t.type);
        return (
          <div
            key={i}
            className={`truthband ${t.detected ? '' : 'is-missed'}`}
            style={{ left, width, ...cssVar('--c', flawColor(t.type)) }}
            title={`Injected: ${meta.label}, ${fmtNum(t.start_s, 1)}–${fmtNum(t.end_s, 1)} s. ${t.detected ? 'The analysis detected it.' : 'The analysis did not detect it.'}`}
          >
            {width >= 80 ? <span>{meta.label}{t.detected ? '' : ' · missed'}</span> : null}
          </div>
        );
      })}
    </div>
  );
});
