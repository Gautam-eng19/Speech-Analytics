import { useRef } from 'react';
import { flawColor } from '@/lib/flawMeta';
import { fmtClock } from '@/lib/format';
import { recordingDuration, analysedSpan } from '@/lib/result';
import { useSettings } from '@/lib/settings';
import { useStore } from '@/lib/store';
import { clamp, minSpan, span } from '@/lib/time';
import { useCurrent } from '@/state/analysis';
import { seek, usePlayhead } from '@/state/player';
import { selectFlaw, selectionStore, setView, viewStore } from '@/state/ui';
import { playerStore } from '@/state/player';

type Mode = 'pan' | 'left' | 'right' | 'click';

/**
 * The delivery ribbon: the whole recording in one strip, always visible on analysis pages. Coloured bands are the flaws, the
 * hatched ends are trimmed silence, the bracket is what the timeline currently shows (drag it, or its edges), the red line is the
 * playhead. Click anywhere to seek.
 */
export function Ribbon() {
  const current = useCurrent();
  const view = useStore(viewStore, (v) => v);
  const playhead = usePlayhead();
  const selected = useStore(selectionStore, (s) => s.flawId);
  const settings = useSettings();
  const track = useRef<HTMLDivElement>(null);
  const drag = useRef<{ mode: Mode; x0: number; start: { t0: number; t1: number }; moved: boolean } | null>(null);

  if (!current) return null;
  const { result } = current;
  const duration = recordingDuration(result);
  const trimmed = analysedSpan(result);
  const pct = (t: number) => `${(clamp(t / duration, 0, 1) * 100).toFixed(3)}%`;
  const timeAt = (clientX: number) => {
    const rect = track.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return 0;
    return clamp((clientX - rect.left) / rect.width, 0, 1) * duration;
  };
  const fullView = span(view) >= duration - 1e-6;

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const handle = target.dataset.handle;
    const inView = !!target.closest('[data-viewport]');
    const mode: Mode = handle === 'left' ? 'left' : handle === 'right' ? 'right' : inView && !fullView ? 'pan' : 'click';
    drag.current = { mode, x0: e.clientX, start: { ...view }, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    const rect = track.current?.getBoundingClientRect();
    if (!d || !rect) return;
    if (Math.abs(e.clientX - d.x0) > 3) d.moved = true;
    if (!d.moved) return;
    const dt = ((e.clientX - d.x0) / rect.width) * duration;
    if (d.mode === 'pan') {
      const width = span(d.start);
      const t0 = clamp(d.start.t0 + dt, 0, duration - width);
      setView({ t0, t1: t0 + width });
    } else if (d.mode === 'left') {
      setView({ t0: clamp(d.start.t0 + dt, 0, d.start.t1 - minSpan(duration)), t1: d.start.t1 });
    } else if (d.mode === 'right') {
      setView({ t0: d.start.t0, t1: clamp(d.start.t1 + dt, d.start.t0 + minSpan(duration), duration) });
    }
  };

  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    drag.current = null;
    if (!d || d.moved) return;
    const t = timeAt(e.clientX);
    if (playerStore.get().src) seek(t);
    // Keep what the user pointed at on screen.
    if (t < view.t0 || t > view.t1) {
      const width = span(view);
      const t0 = clamp(t - width / 2, 0, duration - width);
      setView({ t0, t1: t0 + width });
    }
  };

  const truth = settings.showGroundTruth ? current.sample?.injected ?? [] : [];

  return (
    <div className="ribbon no-print" role="group" aria-label="Whole recording">
      <span className="ribbon__time num">{fmtClock(0, 0)}</span>
      <div
        className="ribbon__track"
        ref={track}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => (drag.current = null)}
        data-pannable={!fullView}
      >
        <div className="ribbon__trim" style={{ left: 0, width: pct(trimmed.start) }} aria-hidden="true" />
        <div className="ribbon__trim" style={{ left: pct(trimmed.end), right: 0 }} aria-hidden="true" />
        {truth.map((t, i) => (
          <div key={`truth-${i}`} className={`ribbon__truth ${t.detected ? '' : 'is-missed'}`} style={{ left: pct(t.start_s), width: pct(t.end_s - t.start_s), ['--c' as string]: flawColor(t.type) }} aria-hidden="true" />
        ))}
        {result.flaws.map((f) => (
          <button
            key={f.flaw_id}
            type="button"
            className={`ribbon__flaw ${selected === f.flaw_id ? 'is-selected' : ''}`}
            style={{ left: pct(f.start_s), width: `max(4px, ${pct(f.end_s - f.start_s)})`, ['--c' as string]: flawColor(f.type) }}
            aria-label={`${f.flaw_id}: ${f.type.replace(/_/g, ' ')}, ${f.start_s.toFixed(1)} to ${f.end_s.toFixed(1)} seconds`}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => selectFlaw(selected === f.flaw_id ? null : f.flaw_id)}
          />
        ))}
        <div className="ribbon__view" data-viewport style={{ left: pct(view.t0), width: pct(span(view)) }}>
          <span className="ribbon__handle ribbon__handle--l" data-handle="left" />
          <span className="ribbon__handle ribbon__handle--r" data-handle="right" />
        </div>
        <div className="ribbon__playhead" style={{ left: pct(playhead) }} aria-hidden="true" />
      </div>
      <span className="ribbon__time num">{fmtClock(duration, 0)}</span>
    </div>
  );
}
