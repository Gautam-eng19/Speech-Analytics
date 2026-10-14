import { Icon } from '@/components/Icon';
import { Button, IconButton, Tip, Kbd } from '@/components/ui';
import { fmtClock, fmtNum } from '@/lib/format';
import { findFlaw, recordingDuration } from '@/lib/result';
import { useStore } from '@/lib/store';
import { useCurrent } from '@/state/analysis';
import { goToFlaw, stepFlaw, togglePlayback } from '@/state/actions';
import { clearRange, seek, setRate, usePlayer, usePlayhead, playerStore } from '@/state/player';
import { selectionStore } from '@/state/ui';

const RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];

/** Playback controls, docked under the page. Hidden when the analysis has no audio (uploads are not stored). */
export function Transport() {
  const current = useCurrent();
  const player = usePlayer();
  const playhead = usePlayhead();
  const selectedId = useStore(selectionStore, (s) => s.flawId);
  if (!current || !player.src) return null;
  const duration = player.duration > 0 ? player.duration : recordingDuration(current.result);
  const selected = findFlaw(current.result, selectedId);
  const looping = player.range?.loop ?? false;

  return (
    <div className="transport no-print" role="group" aria-label="Playback">
      <div className="transport__main">
        <Tip text={<>Previous flaw <Kbd>[</Kbd></>}><IconButton icon="skip-back" label="Previous flaw" onClick={() => stepFlaw(-1)} /></Tip>
        <button type="button" className="transport__play" onClick={togglePlayback} aria-label={player.playing ? 'Pause' : 'Play'} disabled={!player.ready && !player.error}>
          <Icon name={player.playing ? 'pause' : 'play'} size={20} />
        </button>
        <Tip text={<>Next flaw <Kbd>]</Kbd></>}><IconButton icon="skip-forward" label="Next flaw" onClick={() => stepFlaw(1)} /></Tip>
      </div>

      <div className="transport__time num" aria-live="off">
        <span>{fmtClock(playhead)}</span>
        <span className="muted"> / {fmtClock(duration)}</span>
      </div>

      <input
        className="scrubber"
        type="range"
        min={0}
        max={duration}
        step={0.01}
        value={Math.min(playhead, duration)}
        onChange={(e) => seek(Number(e.target.value))}
        aria-label="Seek"
        style={{ ['--p' as string]: `${duration > 0 ? (Math.min(playhead, duration) / duration) * 100 : 0}%` }}
      />

      <div className="transport__side">
        {selected ? (
          <>
            <Button size="sm" variant="secondary" icon="play" onClick={() => goToFlaw(selected, { play: true })}>Play {selected.flaw_id.replace('flaw_', '#')}</Button>
            <Tip text="Loop the selected flaw">
              <IconButton icon="loop" label="Loop selected flaw" active={looping} onClick={() => (looping ? clearRange() : goToFlaw(selected, { play: true, loop: true }))} />
            </Tip>
          </>
        ) : null}
        <label className="rate">
          <span className="sr-only">Playback speed</span>
          <select className="select rate__select num" value={player.rate} onChange={(e) => setRate(Number(e.target.value))} aria-label="Playback speed">
            {RATES.map((r) => <option key={r} value={r}>{fmtNum(r, r % 1 === 0 ? 0 : 2)}×</option>)}
          </select>
        </label>
      </div>
      {player.error ? <div className="transport__error" role="alert">{player.error}</div> : null}
    </div>
  );
}

export const transportVisible = (): boolean => playerStore.get().src !== null;
