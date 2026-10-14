import { useEffect, useId, useRef, useState } from 'react';
import { fmtNum, plural } from '@/lib/format';
import { useWidth } from './useWidth';

/** One dimension of the score, exactly as the backend reported it. `score` is null when the backend did not evaluate it. */
export interface RadarDim {
  key: string;
  label: string;
  score: number | null;
  weight: number;
  flawCount: number;
  penalty: number;
  /** Why there is no score (from the analysis notes), shown instead of a value. */
  reason?: string;
}

/** Clockwise from twelve o'clock. Geometry only: nothing here is analysis. */
export const axisAngle = (index: number, count: number): number => -Math.PI / 2 + (2 * Math.PI * index) / Math.max(1, count);

/** The point at `value` (0 to 100) on the spoke of angle `angle`. */
export function radarPoint(cx: number, cy: number, radius: number, angle: number, value: number): { x: number; y: number } {
  const r = (Math.max(0, Math.min(100, value)) / 100) * radius;
  return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
}

const RINGS = [25, 50, 75, 100] as const;
const FALLBACK_WIDTH = 440;

interface Props {
  dims: readonly RadarDim[];
  activeKey: string | null;
  onActive: (key: string | null) => void;
  /** Called on click, Enter or Space on an axis. */
  onOpen?: (key: string) => void;
  /** What clicking an axis does, for the tooltip ("Open the strongest finding"); only shown for axes that have findings. */
  openHint?: string;
  label: string;
}

/**
 * The score profile: one spoke per scored dimension, the outer ring is 100 (no deviation from the baseline) and the shaded shape is where this
 * delivery stands. The stretch between a corner and the outer ring is what the dimension lost; it is what lights up on hover. A dimension the backend
 * did not evaluate keeps its spoke (dashed) but gets no corner: it is never drawn as perfect, and the shape joins its neighbours.
 * Every number is the backend's; hover, focus (arrow keys move between spokes) and click behave the same, and the list next to it carries the same values as text.
 */
export function ScoreRadar({ dims, activeKey, onActive, onOpen, openHint, label }: Props) {
  const [wrapRef, measured] = useWidth<HTMLDivElement>();
  const width = Math.max(260, measured || FALLBACK_WIDTH);
  const n = dims.length;
  const labelRoom = width < 420 ? 66 : 92;
  const radius = Math.max(66, Math.min(150, width / 2 - labelRoom));
  const height = 2 * radius + 116;
  const cx = width / 2;
  const cy = height / 2;
  const id = useId();
  const axes = useRef<Array<SVGGElement | null>>([]);
  const [tab, setTab] = useState(0);

  useEffect(() => {
    if (tab >= n) setTab(0);
  }, [n, tab]);

  const scored = dims.map((d, i) => ({ d, i })).filter((x): x is { d: RadarDim & { score: number }; i: number } => x.d.score !== null);
  const corner = (d: RadarDim, i: number) => radarPoint(cx, cy, radius, axisAngle(i, n), d.score ?? 0);
  const shape = scored.map(({ d, i }) => corner(d, i));
  const active = dims.find((d) => d.key === activeKey) ?? null;

  const move = (from: number, step: number) => {
    const next = (from + step + n) % n;
    setTab(next);
    axes.current[next]?.focus();
  };

  const onKey = (event: React.KeyboardEvent, index: number, d: RadarDim) => {
    switch (event.key) {
      case 'ArrowRight': case 'ArrowDown': event.preventDefault(); move(index, 1); break;
      case 'ArrowLeft': case 'ArrowUp': event.preventDefault(); move(index, -1); break;
      case 'Home': event.preventDefault(); move(0, 0); break;
      case 'End': event.preventDefault(); move(n - 1, 0); break;
      case 'Enter': case ' ': event.preventDefault(); onOpen?.(d.key); break;
      case 'Escape': (event.currentTarget as SVGGElement).blur(); onActive(null); break;
      default: break;
    }
  };

  // Each spoke owns the wedge of the picture nearest to it, so the pointer only has to be near a spoke, never on its hairline.
  const wedge = (index: number): string => {
    const reach = radius + 40;
    if (n < 3) return `M ${cx - reach} ${cy - reach} h ${2 * reach} v ${2 * reach} h ${-2 * reach} Z`;
    const half = Math.PI / n;
    const a = axisAngle(index, n);
    const from = { x: cx + reach * Math.cos(a - half), y: cy + reach * Math.sin(a - half) };
    const to = { x: cx + reach * Math.cos(a + half), y: cy + reach * Math.sin(a + half) };
    return `M ${cx} ${cy} L ${from.x.toFixed(1)} ${from.y.toFixed(1)} A ${reach} ${reach} 0 0 1 ${to.x.toFixed(1)} ${to.y.toFixed(1)} Z`;
  };

  return (
    <div className="radar" ref={wrapRef}>
      <svg className="radar__svg" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="group" aria-label={label}
        onPointerLeave={() => onActive(null)}>
        <g className="radar__grid" aria-hidden="true">
          {RINGS.map((v) => (
            <polygon key={v} className={`radar__ring ${v === 100 ? 'is-outer' : ''}`}
              points={dims.map((_, i) => { const p = radarPoint(cx, cy, radius, axisAngle(i, n), v); return `${p.x.toFixed(1)},${p.y.toFixed(1)}`; }).join(' ')} />
          ))}
          {[50, 100].map((v) => {
            const p = radarPoint(cx, cy, radius, axisAngle(0, n) + Math.PI / Math.max(2, n), v);
            return <text key={v} className="radar__tick num" x={p.x} y={p.y} textAnchor="middle" dy="-4">{v}</text>;
          })}
        </g>

        <g className="radar__spokes" aria-hidden="true">
          {dims.map((d, i) => {
            const end = radarPoint(cx, cy, radius, axisAngle(i, n), 100);
            return <line key={d.key} className={`radar__spoke ${d.score === null ? 'is-off' : ''} ${d.key === activeKey ? 'is-active' : ''}`} x1={cx} y1={cy} x2={end.x} y2={end.y} />;
          })}
        </g>

        <g className="radar__poly" style={{ ['--cx' as string]: `${cx}px`, ['--cy' as string]: `${cy}px` }}>
          {scored.length >= 3 ? <polygon className="radar__area" points={shape.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')} /> : null}
          {scored.length === 2 ? <line className="radar__edge" x1={shape[0]!.x} y1={shape[0]!.y} x2={shape[1]!.x} y2={shape[1]!.y} /> : null}
          {scored.map(({ d, i }) => {
            const end = radarPoint(cx, cy, radius, axisAngle(i, n), 100);
            const p = corner(d, i);
            return <line key={`gap-${d.key}`} className={`radar__gap ${d.key === activeKey ? 'is-active' : ''}`} x1={p.x} y1={p.y} x2={end.x} y2={end.y} />;
          })}
          {scored.map(({ d, i }) => {
            const p = corner(d, i);
            return <circle key={`dot-${d.key}`} className={`radar__dot ${d.flawCount > 0 ? 'has-findings' : ''} ${d.key === activeKey ? 'is-active' : ''}`} cx={p.x} cy={p.y} r={d.flawCount > 0 ? 5.5 : 4.5} />;
          })}
        </g>

        {dims.map((d, i) => {
          const angle = axisAngle(i, n);
          const at = radarPoint(cx, cy, radius + 14, angle, 100);
          const cos = Math.cos(angle), sin = Math.sin(angle);
          const anchorX = cos > 0.3 ? 'start' : cos < -0.3 ? 'end' : 'middle';
          const top = sin < -0.3, bottom = sin > 0.3;
          const nameY = top ? at.y - 17 : bottom ? at.y + 11 : at.y - 2;
          const valueY = top ? at.y - 3 : bottom ? at.y + 26 : at.y + 12;
          const aria = d.score === null
            ? `${d.label}: not scored. ${d.reason ?? ''}`.trim()
            : `${d.label}: ${fmtNum(d.score, 1)} out of 100, ${plural(d.flawCount, 'finding')}.${d.flawCount > 0 && onOpen ? ' Press Enter to open the strongest one.' : ''}`;
          return (
            <g
              key={d.key} ref={(node) => { axes.current[i] = node; }}
              className={`radar__axis ${d.key === activeKey ? 'is-active' : ''} ${d.score === null ? 'is-off' : ''}`}
              role="button" aria-label={aria} aria-describedby={d.key === activeKey && active ? `${id}-readout` : undefined}
              tabIndex={i === tab ? 0 : -1}
              onPointerEnter={() => onActive(d.key)} onFocus={() => { setTab(i); onActive(d.key); }} onBlur={() => onActive(null)}
              onClick={() => onOpen?.(d.key)} onKeyDown={(e) => onKey(e, i, d)}
            >
              <path className="radar__hit" d={wedge(i)} />
              <rect className="radar__hit" x={anchorX === 'end' ? at.x - 96 : anchorX === 'start' ? at.x : at.x - 48} y={top ? at.y - 34 : bottom ? at.y - 6 : at.y - 16} width={96} height={38} />
              <text className="radar__name" x={at.x} y={nameY} textAnchor={anchorX}>{d.label}</text>
              <text className="radar__value num" x={at.x} y={valueY} textAnchor={anchorX}>{d.score === null ? 'not scored' : fmtNum(d.score, 1)}</text>
            </g>
          );
        })}
      </svg>

      <div id={`${id}-readout`} className={`radar__readout ${active ? 'is-live' : ''}`} aria-live="off">
        {active ? (
          active.score !== null ? (
            <>
              <span className="radar__readout-name">{active.label}</span>
              <span className="radar__readout-value num">{fmtNum(active.score, 1)}<span> / 100</span></span>
              <span className="radar__readout-row num">{active.penalty > 0 ? `lost ${fmtNum(active.penalty, 1)} points` : 'nothing lost'} · weight {fmtNum(active.weight * 100, 0)} % · {plural(active.flawCount, 'finding')}</span>
              {active.flawCount > 0 && onOpen && openHint ? <span className="radar__readout-hint">{openHint}</span> : null}
            </>
          ) : (
            <>
              <span className="radar__readout-name">{active.label}</span>
              <span className="radar__readout-row">{active.reason ?? 'The backend did not evaluate this dimension for this analysis.'}</span>
            </>
          )
        ) : (
          <span className="radar__readout-row radar__readout-idle">Point at a spoke to see what that dimension lost. The outer ring is 100: no deviation from the baseline.</span>
        )}
      </div>
    </div>
  );
}
