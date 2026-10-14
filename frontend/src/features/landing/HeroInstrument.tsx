import { useCallback, useEffect, useId, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent } from 'react';
import { useWidth } from '@/charts/useWidth';
import { Icon } from '@/components/Icon';
import { flawMeta } from '@/lib/flawMeta';
import { fmtClock, fmtNum } from '@/lib/format';
import { readAt } from '@/lib/lookup';
import { nearestIndex } from '@/lib/time';
import { useCoarsePointer, useMotionAllowed } from '@/lib/useMotion';
import { pause as pauseAppPlayer } from '@/state/player';
import { buildScene, illustrativeInput, inputFromResult, tierHeight, type HeroScene, type SceneFlag } from './heroModel';
import type { DemoSample } from './useDemoSample';

/**
 * The landing page's instrument: the speech rate of the demo recording against the reference corridor, the loudness envelope under it,
 * and a marked, labelled interval wherever the pipeline reported a deviation. Everything drawn is read from one real analysis result;
 * without one it shows a labelled illustration instead.
 *
 * Pointer response: the cursor reads out the measurement at that moment (a lookup in the result, nothing computed), lights the bars
 * under it, and shifts only the atmosphere behind the data (grid, glow). Data and text never move. All of it is written straight to the
 * DOM through refs and CSS variables on one listener, so a moving pointer never re-renders React; it is off for coarse pointers and
 * reduced motion.
 */

type ReadKey = 'time' | 'word' | 'loud' | 'pitch' | 'rate' | 'find';
const READ_ROWS: { key: ReadKey; label: string }[] = [
  { key: 'time', label: 'Time' }, { key: 'word', label: 'Word' }, { key: 'rate', label: 'Pace' },
  { key: 'loud', label: 'Loudness' }, { key: 'pitch', label: 'Pitch' }, { key: 'find', label: 'Finding' },
];
const IDLE: Record<ReadKey, string> = { time: '–', word: '–', rate: '–', loud: '–', pitch: '–', find: '–' };

const supportsMotionPath = (): boolean => typeof CSS !== 'undefined' && typeof CSS.supports === 'function' && CSS.supports('offset-path', 'path("M0 0")');

function Bars({ scene, className }: { scene: HeroScene; className: string }) {
  const { bars, mid, barWidth } = scene.loud;
  return (
    <g className={className}>
      {bars.map((b, i) => (
        <rect key={i} className={b.hot ? 'hx-bar hx-bar--hot' : 'hx-bar'} x={b.x} y={mid - b.h} width={barWidth} height={b.h * 2} rx={Math.min(1.6, barWidth / 2)} />
      ))}
    </g>
  );
}

export function HeroInstrument({ sample, loading }: { sample: DemoSample | null; loading: boolean }) {
  const [stageRef, width] = useWidth<HTMLDivElement>();
  const motion = useMotionAllowed();
  const coarse = useCoarsePointer();
  const clipId = useId();
  const result = sample?.result ?? null;

  const scene = useMemo(() => {
    if (width <= 0 || loading) return null;
    return buildScene(result ? inputFromResult(result) : illustrativeInput(), width);
  }, [result, width, loading]);

  const audioRef = useRef<HTMLAudioElement>(null);
  const playedRef = useRef<HTMLDivElement>(null);
  const headRef = useRef<HTMLDivElement>(null);
  const headTimeRef = useRef<HTMLSpanElement>(null);
  const probeRef = useRef<HTMLDivElement>(null);
  const dotRef = useRef<HTMLElement>(null);
  const clockRef = useRef<HTMLSpanElement>(null);
  const readRef = useRef<Record<ReadKey, HTMLElement | null>>({ time: null, word: null, rate: null, loud: null, pitch: null, find: null });
  const rangeEnd = useRef<number | null>(null);
  const liveFlaw = useRef<string | null>(null);
  const pointerInside = useRef(false);
  const [playing, setPlaying] = useState(false);
  const [audioError, setAudioError] = useState(false);
  const [onScreen, setOnScreen] = useState(true);
  const [runner] = useState(supportsMotionPath);

  const interactive = !!result && !!scene && !scene.illustrative;

  // ---- readout: a lookup in the result at one moment ------------------------------------------------------------------------
  const writeReadout = useCallback((t: number | null) => {
    const cells = readRef.current;
    const set = (key: ReadKey, text: string) => { const el = cells[key]; if (el && el.textContent !== text) el.textContent = text; };
    if (t === null || !result) {
      (Object.keys(IDLE) as ReadKey[]).forEach((k) => set(k, IDLE[k]));
      return;
    }
    const r = readAt(result, t);
    set('time', fmtClock(t, 1));
    set('word', r.word ? r.word.word : r.pause ? 'in a pause' : 'between words');
    set('rate', r.rate ? `${fmtNum(r.rate.wpm, 0)} words/min` : 'outside the analysed audio');
    set('loud', r.loudnessDb === null ? 'outside the analysed audio' : `${fmtNum(r.loudnessDb, 1)} dBFS`);
    set('pitch', r.f0Hz === null ? 'outside the analysed audio' : r.f0Hz === 'unvoiced' ? 'unvoiced' : `${fmtNum(r.f0Hz, 0)} Hz`);
    set('find', r.flaws.length ? r.flaws.map((f) => flawMeta(f.type).label).join(', ') : 'none here');
  }, [result]);

  const probeTo = useCallback((t: number | null) => {
    const probe = probeRef.current;
    if (!probe || !scene) return;
    if (t === null) {
      probe.style.opacity = '0';
      return;
    }
    probe.style.transform = `translate3d(${scene.toX(t).toFixed(1)}px,0,0)`;
    probe.style.opacity = '1';
    if (result && dotRef.current) {
      // The dot sits on the nearest rate sample of the trace, like a data cursor snapping to a point.
      const rate = result.features.speech_rate_timeline;
      const i = nearestIndex(rate.times_s, t);
      if (i >= 0) {
        const dx = scene.toX(rate.times_s[i] as number) - scene.toX(t);
        dotRef.current.style.transform = `translate3d(${dx.toFixed(1)}px,${(scene.rate.toY(rate.words_per_min[i] as number) - scene.rate.top).toFixed(1)}px,0)`;
      }
    }
    writeReadout(t);
  }, [scene, result, writeReadout]);

  // ---- playback-linked highlighting: played tint, playhead, the finding being played --------------------------------------------
  const markLive = useCallback((id: string | null) => {
    if (liveFlaw.current === id) return;
    liveFlaw.current = id;
    const root = stageRef.current;
    if (!root) return;
    root.querySelectorAll('.is-live').forEach((el) => el.classList.remove('is-live'));
    if (id) root.querySelectorAll(`[data-flaw="${id.replace(/["\\]/g, '')}"]`).forEach((el) => el.classList.add('is-live'));
  }, [stageRef]);

  const movePlayhead = useCallback((t: number) => {
    if (!scene) return;
    const x = scene.toX(t);
    if (headRef.current) { headRef.current.style.transform = `translate3d(${x.toFixed(1)}px,0,0)`; headRef.current.style.opacity = '1'; }
    if (playedRef.current) playedRef.current.style.transform = `scaleX(${Math.min(1, Math.max(0, t / scene.duration)).toFixed(4)})`;
    const label = fmtClock(t, 1);
    if (headTimeRef.current && headTimeRef.current.textContent !== label) headTimeRef.current.textContent = label;
    if (clockRef.current && clockRef.current.textContent !== label) clockRef.current.textContent = label;
    const f = scene.flags.find((flag) => !scene.illustrative && t >= flag.start && t <= flag.end);
    markLive(f ? f.id : null);
    if (!pointerInside.current) { probeTo(null); writeReadout(t); }
  }, [scene, markLive, probeTo, writeReadout]);

  useEffect(() => {
    const a = audioRef.current;
    if (a && scene && a.currentTime > 0) movePlayhead(a.currentTime);
  }, [scene, movePlayhead]);

  useEffect(() => {
    if (!playing || !onScreen) return;
    let frame = 0;
    const tick = () => {
      const a = audioRef.current;
      if (!a) return;
      if (rangeEnd.current !== null && a.currentTime >= rangeEnd.current) {
        rangeEnd.current = null;
        a.pause();
      }
      movePlayhead(a.currentTime);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, onScreen, movePlayhead]);

  const play = useCallback((from?: number, to?: number) => {
    const a = audioRef.current;
    if (!a) return;
    if (from !== undefined) { a.currentTime = from; movePlayhead(from); }
    rangeEnd.current = to ?? null;
    pauseAppPlayer(); // one voice at a time: the app's own player stops if it was running
    void a.play().catch(() => setAudioError(true));
  }, [movePlayhead]);

  const toggle = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) play(a.ended ? 0 : undefined);
    else a.pause();
  };

  // ---- pointer: one listener on the stage, written to CSS variables and refs --------------------------------------------------
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage || !scene) return;
    let frame = 0;
    let latest: PointerEvent | null = null;
    const react = motion && !coarse;

    const apply = () => {
      frame = 0;
      const e = latest;
      if (!e) return;
      const rect = stage.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      if (react) {
        stage.style.setProperty('--px', ((x / rect.width) * 2 - 1).toFixed(3));
        stage.style.setProperty('--py', ((y / rect.height) * 2 - 1).toFixed(3));
        stage.style.setProperty('--hx', `${x.toFixed(0)}px`);
        stage.style.setProperty('--hy', `${y.toFixed(0)}px`);
      }
      if (interactive) {
        const t = scene.toTime(x);
        probeTo(t);
        const hot = scene.flags.find((f) => t >= f.start && t <= f.end);
        stage.querySelectorAll('.is-hot').forEach((el) => { if (!hot || el.getAttribute('data-flaw') !== hot.id) el.classList.remove('is-hot'); });
        if (hot) stage.querySelectorAll(`[data-flaw="${hot.id.replace(/["\\]/g, '')}"]`).forEach((el) => el.classList.add('is-hot'));
      }
    };
    const onMove = (e: PointerEvent) => {
      latest = e;
      if (!frame) frame = requestAnimationFrame(apply);
    };
    const onEnter = () => { pointerInside.current = true; stage.dataset.active = 'true'; };
    const onLeave = () => {
      pointerInside.current = false;
      latest = null;
      stage.dataset.active = 'false';
      stage.style.setProperty('--px', '0');
      stage.style.setProperty('--py', '0');
      stage.querySelectorAll('.is-hot').forEach((el) => el.classList.remove('is-hot'));
      probeTo(null);
      const a = audioRef.current;
      writeReadout(a && (a.currentTime > 0 || !a.paused) ? a.currentTime : null);
    };
    stage.addEventListener('pointermove', onMove);
    stage.addEventListener('pointerenter', onEnter);
    stage.addEventListener('pointerleave', onLeave);
    return () => {
      cancelAnimationFrame(frame);
      stage.removeEventListener('pointermove', onMove);
      stage.removeEventListener('pointerenter', onEnter);
      stage.removeEventListener('pointerleave', onLeave);
      pointerInside.current = false;
    };
  }, [stageRef, scene, motion, coarse, interactive, probeTo, writeReadout]);

  // ---- pause everything that moves while the instrument is out of view ----------------------------------------------------------
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(([entry]) => setOnScreen(entry ? entry.isIntersecting : true), { threshold: 0.05 });
    observer.observe(stage);
    return () => observer.disconnect();
  }, [stageRef]);

  // The audio belongs to this page: it stops when the page goes away. (A stable ref callback, so that it is not stopped by an ordinary re-render.)
  const attachAudio = useCallback((element: HTMLAudioElement | null) => {
    audioRef.current = element;
    return () => { element?.pause(); };
  }, []);

  const onStageClick = (e: ReactMouseEvent<HTMLDivElement>) => {
    if (!interactive || !scene || (e.target as HTMLElement).closest('button, a')) return;
    const rect = e.currentTarget.getBoundingClientRect();
    play(scene.toTime(e.clientX - rect.left));
  };

  const height = scene?.height ?? 372;
  const duration = result ? scene?.duration ?? 0 : 0;
  const summary = interactive
    ? `Demo sample, ${fmtClock(scene.duration, 1)} long. ${scene.flags.length === 0 ? 'No deviations were detected.' : `${scene.flags.length} deviation${scene.flags.length === 1 ? '' : 's'} detected: ${scene.flags.map((f) => `${f.label} from ${fmtClock(f.start, 1)} to ${fmtClock(f.end, 1)}${f.evidence ? `, ${f.evidence}` : ''}`).join('; ')}.`}`
    : 'An illustration of the instrument: speech rate and loudness over time, with one deviation marked. It does not show a measurement.';

  return (
    <div className="hxw">
      <div
        ref={stageRef}
        className="hx"
        role="group"
        aria-label="Instrument: speech rate and loudness of a demo recording against the reference"
        data-motion={motion ? 'on' : 'off'}
        data-paused={onScreen ? 'false' : 'true'}
        data-playing={playing ? 'true' : 'false'}
        data-active="false"
        data-ready={scene ? 'true' : 'false'}
        data-live-data={interactive ? 'true' : 'false'}
        onClick={onStageClick}
        style={{ height }}
      >
        <p className="sr-only">{summary}</p>
        <div className="hx__depth hx__depth--far" aria-hidden="true"><div className="hx__glow" /></div>
        <div className="hx__depth hx__depth--back" aria-hidden="true"><div className="hx__grid" /></div>
        <div className="hx__light" aria-hidden="true" />

        {scene ? (
          <>
            <svg className="hx__data" width={scene.width} height={scene.height} viewBox={`0 0 ${scene.width} ${scene.height}`} aria-hidden="true" focusable="false">
              <defs>
                <linearGradient id={`${clipId}-fill`} x1="0" y1="0" x2="0" y2="1">
                  <stop className="hx-area-stop--top" offset="0" />
                  <stop className="hx-area-stop--bottom" offset="1" />
                </linearGradient>
                <clipPath id={clipId}>
                  {scene.flags.map((f) => <rect key={f.id} x={f.x0} y={scene.rate.top} width={Math.max(1, f.x1 - f.x0)} height={scene.rate.bottom - scene.rate.top} />)}
                </clipPath>
              </defs>

              {/* frame: track rules and the time grid */}
              <g className="hx-frame">
                {scene.axis.ticks.map((t) => <line key={t.x} className="hx-tick" x1={t.x} x2={t.x} y1={scene.rate.top} y2={scene.axis.top + 5} />)}
                <line className="hx-rule" x1={0} x2={scene.width} y1={scene.rate.top} y2={scene.rate.top} />
                <line className="hx-rule" x1={0} x2={scene.width} y1={scene.rate.bottom} y2={scene.rate.bottom} />
                <line className="hx-rule" x1={0} x2={scene.width} y1={scene.loud.bottom} y2={scene.loud.bottom} />
                <line className="hx-rule hx-rule--mid" x1={0} x2={scene.width} y1={scene.loud.mid} y2={scene.loud.mid} />
              </g>

              {/* the reference: a steel corridor (mean ± 1 and 2 standard deviations) */}
              {scene.rate.band2 ? <rect className="hx-band hx-band--2" x={0} width={scene.width} y={scene.rate.band2[0]} height={Math.max(0, scene.rate.band2[1] - scene.rate.band2[0])} /> : null}
              {scene.rate.band1 ? <rect className="hx-band hx-band--1" x={0} width={scene.width} y={scene.rate.band1[0]} height={Math.max(0, scene.rate.band1[1] - scene.rate.band1[0])} /> : null}
              {scene.rate.mean !== null ? <line className="hx-mean" x1={0} x2={scene.width} y1={scene.rate.mean} y2={scene.rate.mean} /> : null}

              {/* deviations: a copper veil through both tracks and a bracket over the interval */}
              {scene.flags.map((f) => (
                <g key={f.id} className="hx-dev" data-flaw={f.id}>
                  <rect className="hx-dev__veil" x={f.x0} y={scene.rate.top} width={Math.max(1, f.x1 - f.x0)} height={scene.loud.bottom - scene.rate.top} />
                  <path className="hx-dev__bracket" d={`M${f.x0} ${scene.rate.top + 4}V${scene.rate.top - 5}H${f.x1}V${scene.rate.top + 4}`} />
                </g>
              ))}

              {/* loudness: a mirrored envelope, copper where it lies inside a deviation */}
              <Bars scene={scene} className="hx-bars" />

              {/* delivery: the speech-rate trace */}
              <path className="hx-area" d={scene.rate.area} fill={`url(#${clipId}-fill)`} />
              <path className="hx-trace" d={scene.rate.line} />
              <path className="hx-trace hx-trace--dev" d={scene.rate.line} clipPath={`url(#${clipId})`} />

              {/* labels */}
              <g className="hx-labels">
                <text className="hx-label" x={14} y={scene.rate.bottom - (scene.rate.corridorLabel ? 22 : 10)}>{scene.illustrative ? 'SPEECH RATE' : 'SPEECH RATE · WORDS/MIN'}</text>
                {scene.rate.corridorLabel ? <text className="hx-label hx-label--dim" x={14} y={scene.rate.bottom - 9}>{scene.rate.corridorLabel}</text> : null}
                <text className="hx-label" x={14} y={scene.loud.top - 6}>LOUDNESS · DBFS</text>
                {!scene.illustrative ? scene.rate.ticks.map((t) => <text key={t.label + t.y} className="hx-ytick" x={scene.width - 10} y={t.y + 3.5} textAnchor="end">{t.label}</text>) : null}
                {scene.axis.ticks.map((t) => (t.label ? <text key={t.x} className="hx-axis" x={t.x + 6} y={scene.axis.top + 15}>{t.label}</text> : null))}
              </g>
            </svg>

            {/* the same bars again, brighter, shown only under the pointer */}
            <div className="hx__lit" aria-hidden="true">
              <svg width={scene.width} height={scene.height} viewBox={`0 0 ${scene.width} ${scene.height}`} focusable="false"><Bars scene={scene} className="hx-bars hx-bars--lit" /></svg>
            </div>

            <div className="hx__live" aria-hidden="true" style={{ top: scene.rate.top, height: scene.axis.top - scene.rate.top }}>
              <div ref={playedRef} className="hx__played" />
              <div ref={probeRef} className="hx__probe"><i ref={dotRef} className="hx__probe-dot" /></div>
              <div ref={headRef} className="hx__head"><span ref={headTimeRef} className="hx__head-time num">0:00.0</span></div>
            </div>

            {runner && motion && scene.rate.line ? <i className="hx-runner" aria-hidden="true" style={{ offsetPath: `path('${scene.rate.line}')` } as CSSProperties} /> : null}

            <div className="hx__flags">
              {scene.flags.map((f, i) => <Flag key={f.id} flag={f} scene={scene} index={i} interactive={interactive} onPlay={() => play(f.start, f.end)} />)}
            </div>
          </>
        ) : (
          <div className="hx__wait" aria-hidden="true"><span className="spinner" /></div>
        )}
      </div>

      <div className="hx__foot">
        <div className="hx__transport">
          <button
            type="button"
            className="hx-play"
            onClick={toggle}
            disabled={!interactive || audioError}
            aria-label={playing ? 'Pause the demo recording' : 'Play the demo recording'}
            aria-pressed={playing}
          >
            <Icon name={playing ? 'pause' : 'play'} size={18} />
          </button>
          <div className="hx__clock num" aria-hidden="true"><span ref={clockRef}>0:00.0</span><span className="muted"> / {duration > 0 ? fmtClock(duration, 1) : '–'}</span></div>
        </div>

        <p className="hx__source">
          {interactive ? (
            <><Icon name="flask" size={13} /> <span><strong>Demo sample.</strong> A synthetic voice, analysed by the real pipeline. Hover the trace to read a moment, click it to hear it.</span></>
          ) : loading ? (
            <span className="muted">Loading the demo sample…</span>
          ) : (
            <><Icon name="info" size={13} /> <span><strong>Illustration.</strong> The demo sample could not be loaded, so this is a drawing of the instrument, not a measurement.</span></>
          )}
        </p>

        <dl className="hx__read" aria-label="Measurement at the cursor">
          {READ_ROWS.map((row) => (
            <div key={row.key} className="hx__read-row">
              <dt>{row.label}</dt>
              <dd className="num" ref={(el) => { readRef.current[row.key] = el; }}>{IDLE[row.key]}</dd>
            </div>
          ))}
        </dl>
      </div>

      {sample ? <audio ref={attachAudio} src={sample.audioUrl} preload="metadata" onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => { setPlaying(false); rangeEnd.current = null; }} onError={() => setAudioError(true)} /> : null}
    </div>
  );
}

function Flag({ flag, scene, index, interactive, onPlay }: { flag: SceneFlag; scene: HeroScene; index: number; interactive: boolean; onPlay: () => void }) {
  const meta = flag.type === 'illustration' ? null : flawMeta(flag.type);
  const tierH = tierHeight(scene.compact);
  const top = 8 + flag.tier * tierH;
  const boxH = tierH - 10;
  const delay = `${(0.5 + (flag.x0 / Math.max(1, scene.width)) * 1.1).toFixed(2)}s`;
  const style = { left: flag.left, top, width: flag.width, height: boxH, ['--d' as string]: delay } as CSSProperties;
  const label = interactive
    ? `${flag.label}, ${flag.interval}${flag.evidence ? `, ${flag.evidence}` : ''}. Play this moment.`
    : `${flag.label} (illustration)`;
  const inner = (
    <>
      <span className="hx-flag__head"><Icon name={meta ? meta.icon : 'flag'} size={12} /><span className="hx-flag__type">{flag.label}</span>{scene.compact ? null : <span className="hx-flag__when num">{flag.interval}</span>}</span>
      {flag.evidence ? <span className="hx-flag__ev num">{flag.evidence}</span> : null}
    </>
  );
  const leader = <i className="hx-leader" data-flaw={flag.id} style={{ left: flag.x0, top: top + boxH, height: Math.max(0, scene.rate.top - 5 - (top + boxH)), ['--d' as string]: delay } as CSSProperties} />;
  return (
    <>
      {leader}
      {interactive ? (
        <button type="button" className="hx-flag" data-flaw={flag.id} style={style} aria-label={label} onClick={onPlay} data-index={index}>{inner}</button>
      ) : (
        <div className="hx-flag hx-flag--static" data-flaw={flag.id} style={style} role="img" aria-label={label}>{inner}</div>
      )}
    </>
  );
}
