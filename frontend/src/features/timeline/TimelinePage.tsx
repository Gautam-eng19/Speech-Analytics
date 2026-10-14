import { useEffect, useMemo } from 'react';
import { laneHeights, type LaneKey } from '@/charts/geometry';
import { TimelineStack } from '@/charts/TimelineStack';
import { useSize } from '@/charts/useWidth';
import { Button, IconButton, Kbd, Tip, ToggleChip } from '@/components/ui';
import { fmtNum } from '@/lib/format';
import { findFlaw, recordingDuration } from '@/lib/result';
import { LANE_TOGGLES, updateSettings, useSettings, useTimecode, type LaneToggle } from '@/lib/settings';
import { useStore } from '@/lib/store';
import { clamp, FULL, span, zoomAt } from '@/lib/time';
import { goToFlaw } from '@/state/actions';
import type { LoadedAnalysis } from '@/state/analysis';
import { playerStore, playheadStore, seek } from '@/state/player';
import { selectionStore, selectFlaw, setView, viewStore } from '@/state/ui';
import { AtCursor, Legend, SelectedFinding } from './Inspector';

const LANE_LABEL: Record<LaneToggle, string> = { words: 'Words', loudness: 'Loudness', pitch: 'Pitch', rate: 'Rate', pauses: 'Pauses' };

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable;
}

/**
 * The scope: every signal on one shared time axis with the findings above it. Scroll to zoom around the pointer, drag or Shift+scroll
 * to pan, double-click to fit; the crosshair and the readout on the right follow the pointer, the red line follows playback.
 */
export function TimelinePage({ analysis }: { analysis: LoadedAnalysis }) {
  const { result, sample } = analysis;
  const settings = useSettings();
  const tc = useTimecode();
  const view = useStore(viewStore, (v) => v);
  const selectedId = useStore(selectionStore, (s) => s.flawId);
  const hasAudio = useStore(playerStore, (s) => s.src !== null);
  const duration = recordingDuration(result);
  const selected = findFlaw(result, selectedId);
  const zoomed = span(view) < duration - 1e-6;

  const lanes = useMemo<LaneKey[]>(() => ['flaws', ...LANE_TOGGLES.filter((lane) => settings.lanes[lane])], [settings.lanes]);

  // The signal lanes grow (up to 80 %) to use the height that is left, so the picture fills the screen instead of a strip of it.
  const [mainRef, mainSize] = useSize<HTMLDivElement>();
  const truthShown = !!sample && settings.showGroundTruth && sample.injected.length > 0;
  const heights = useMemo(() => {
    const base = laneHeights(false);
    const grow: LaneKey[] = lanes.filter((k) => k === 'loudness' || k === 'pitch' || k === 'rate' || k === 'pauses');
    const fixed = (['axis', ...lanes, ...(truthShown ? (['truth'] as LaneKey[]) : [])] as LaneKey[]).reduce((sum, k) => sum + base[k], 0);
    const flexible = grow.reduce((sum, k) => sum + base[k], 0);
    const spare = mainSize.height - 2 * 20 - 40 - 2 - fixed;
    const factor = flexible > 0 && spare > 0 ? 1 + Math.min(spare / flexible, 0.8) : 1;
    return Object.fromEntries(grow.map((k) => [k, Math.round(base[k] * factor)])) as Partial<Record<LaneKey, number>>;
  }, [lanes, truthShown, mainSize.height]);

  const zoom = (factor: number) => {
    const v = viewStore.get();
    const t = playheadStore.get();
    const anchor = playerStore.get().src && t >= v.t0 && t <= v.t1 ? t : (v.t0 + v.t1) / 2;
    setView(zoomAt(v, factor, anchor, duration));
  };

  // Keyboard: + and - zoom, 0 fits.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented || isTyping(e.target)) return;
      if (e.key === '+' || e.key === '=') { e.preventDefault(); zoom(1.5); }
      else if (e.key === '-' || e.key === '_') { e.preventDefault(); zoom(1 / 1.5); }
      else if (e.key === '0') { e.preventDefault(); setView(FULL(duration)); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [duration]);

  // Follow the playhead while playing: when it nears the right edge or leaves the view, page the view along.
  useEffect(() => {
    if (!settings.followPlayhead) return;
    return playheadStore.subscribe(() => {
      if (!playerStore.get().playing) return;
      const t = playheadStore.get();
      const v = viewStore.get();
      const width = span(v);
      if (width >= duration - 1e-6) return;
      if (t > v.t1 - width * 0.08 || t < v.t0) {
        const t0 = clamp(t - width * 0.2, 0, duration - width);
        setView({ t0, t1: t0 + width });
      }
    });
  }, [settings.followPlayhead, duration]);

  return (
    <div className="scope">
      <div className="scope__bar" role="toolbar" aria-label="Timeline controls">
        <div className="scope__group">
          <Tip text={<>Zoom out <Kbd>−</Kbd></>}><IconButton icon="zoom-out" label="Zoom out" onClick={() => zoom(1 / 1.5)} disabled={!zoomed} /></Tip>
          <Tip text={<>Zoom in <Kbd>+</Kbd></>}><IconButton icon="zoom-in" label="Zoom in" onClick={() => zoom(1.5)} /></Tip>
          <Tip text={<>Fit the whole recording <Kbd>0</Kbd></>}><IconButton icon="fit" label="Fit the whole recording" onClick={() => setView(FULL(duration))} disabled={!zoomed} /></Tip>
          <Button size="sm" variant="ghost" icon="target" disabled={!selected} onClick={() => selected && goToFlaw(selected)}>Selection</Button>
        </div>
        <div className="scope__window num" aria-live="off">
          <span>{tc.range(view.t0, view.t1)}</span>
          <span className="muted">{fmtNum(span(view), 1)} s · ×{fmtNum(duration / span(view), 1)}</span>
        </div>
        <div className="scope__spacer" />
        <div className="scope__group scope__lanes" role="group" aria-label="Lanes">
          {LANE_TOGGLES.map((lane) => (
            <ToggleChip key={lane} on={settings.lanes[lane]} onChange={(on) => updateSettings({ lanes: { ...settings.lanes, [lane]: on } })}>{LANE_LABEL[lane]}</ToggleChip>
          ))}
          {sample ? <ToggleChip on={settings.showGroundTruth} icon="flask" onChange={(on) => updateSettings({ showGroundTruth: on })} title="Show where the synthetic sample was given a known flaw">Ground truth</ToggleChip> : null}
          <ToggleChip on={settings.followPlayhead} icon="link" onChange={(on) => updateSettings({ followPlayhead: on })} title="Scroll the view with the playhead while playing">Follow</ToggleChip>
        </div>
      </div>

      <div className="scope__body">
        <div className="scope__main" ref={mainRef}>
          <TimelineStack
            analysis={analysis}
            lanes={lanes}
            heights={heights}
            view={view}
            onView={setView}
            selected={selected}
            onSelect={(f) => { selectFlaw(selectedId === f.flaw_id ? null : f.flaw_id); if (selectedId !== f.flaw_id && hasAudio) seek(f.start_s); }}
            onPlotClick={(t) => seek(t)}
            showTruth={settings.showGroundTruth}
            label="Timeline of the recording: findings and signals on one time axis"
          />
          <p className="scope__hint">
            <span>Scroll to zoom</span><span>Shift + scroll or drag to pan</span><span>Double-click to fit</span><span>Click to move the playhead</span>
            {hasAudio ? null : <span>No audio for this analysis: uploads are analysed but not stored</span>}
          </p>
        </div>
        <aside className="scope__side" aria-label="Inspector" tabIndex={0}>
          <AtCursor analysis={analysis} />
          <SelectedFinding analysis={analysis} flaw={selected} />
          <Legend hasTruth={!!sample && settings.showGroundTruth && sample.injected.length > 0} />
        </aside>
      </div>
    </div>
  );
}

