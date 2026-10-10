import { useEffect, useReducer, useRef, useState } from 'react';
import { Icon } from '@/components/Icon';
import { Button, Chip } from '@/components/ui';
import { fmtBytes, fmtClock } from '@/lib/format';
import { browserEnv, createRecorder, describeError, listMicrophones, MAX_RECORD_S, type CaptureInfo, type Recorder, type RecorderEvents, type Take } from '@/recording/recorder';
import { pushToast } from '@/state/ui';
import { PreviewPlayer } from './PreviewPlayer';

type Phase = 'idle' | 'starting' | 'recording' | 'finishing' | 'ready';

const HISTORY = 160;
const FLOOR_DB = -60;
/** Level on a decibel scale, 0 at the floor and 1 at full scale, so quiet speech still moves the bar. */
const levelFraction = (peak: number) => Math.max(0, Math.min(1, (20 * Math.log10(Math.max(peak, 1e-5)) - FLOOR_DB) / -FLOOR_DB));

export interface RecorderPanelProps {
  /** The passage the chosen baseline describes, shown as the prompt. */
  passage: { title: string; text: string } | null;
  onUse: (file: File) => void;
  disabled?: boolean;
  /** Test seam: how a recorder is made. */
  makeRecorder?: (events: RecorderEvents) => Recorder;
}

/**
 * Recording in the browser. The microphone is opened with voice processing off, the samples are kept raw and written as a 16 kHz
 * WAV that goes through the same upload form as a file (see src/recording/recorder.ts). The level bar is for setting the microphone;
 * the analysis, as always, happens on the server.
 */
export function RecorderPanel({ passage, onUse, disabled, makeRecorder = (events) => createRecorder(browserEnv(), events) }: RecorderPanelProps) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const [take, setTake] = useState<Take | null>(null);
  const [capture, setCapture] = useState<CaptureInfo | null>(null);
  const [devices, setDevices] = useState<{ id: string; label: string }[]>([]);
  const [deviceId, setDeviceId] = useState('');
  const recorder = useRef<Recorder | null>(null);
  const levels = useRef<number[]>([]);
  const latest = useRef({ peak: 0, elapsedS: 0 });
  const [, repaint] = useReducer((n: number) => n + 1, 0);

  // Redraw the level history on animation frames while recording (the recorder reports about 45 blocks a second).
  useEffect(() => {
    if (phase !== 'recording') return;
    let frame = requestAnimationFrame(function loop() {
      repaint();
      frame = requestAnimationFrame(loop);
    });
    return () => cancelAnimationFrame(frame);
  }, [phase]);

  // Leaving the page must release the microphone.
  useEffect(() => () => recorder.current?.cancel(), []);

  const finish = async (reachedLimit = false) => {
    const active = recorder.current;
    if (!active) return;
    setPhase('finishing');
    try {
      const result = await active.stop();
      levels.current = [];
      latest.current = { peak: 0, elapsedS: 0 };
      setTake(result);
      setPhase('ready');
      if (reachedLimit) pushToast(`Stopped at ${Math.round(MAX_RECORD_S / 60)} minutes, the longest recording the server accepts by default.`, 'info', 6000);
    } catch (e) {
      setError(describeError(e).message);
      setPhase('idle');
    } finally {
      recorder.current = null;
    }
  };

  const start = async () => {
    setError(null);
    setTake(null);
    setPhase('starting');
    const next = makeRecorder({
      onLevel: (reading) => {
        levels.current.push(reading.peak);
        if (levels.current.length > HISTORY) levels.current.shift();
        latest.current = { peak: reading.peak, elapsedS: reading.elapsedS };
      },
      onLimit: () => void finish(true),
    });
    recorder.current = next;
    try {
      levels.current = [];
      latest.current = { peak: 0, elapsedS: 0 };
      setCapture(await next.start({ deviceId: deviceId || undefined }));
      setPhase('recording');
      listMicrophones().then(setDevices).catch(() => undefined);
    } catch (e) {
      recorder.current = null;
      setError(describeError(e).message);
      setPhase('idle');
    }
  };

  const recording = phase === 'recording';
  const recent = levels.current;
  const holdPeak = recent.slice(-45).reduce((m, v) => Math.max(m, v), 0);
  const processed = capture && (capture.echoCancellation || capture.noiseSuppression || capture.autoGainControl);

  return (
    <div className="rec">
      {passage ? (
        <section className="rec__prompt" aria-label="Passage to read">
          <div className="eyebrow">Read this aloud at your normal pace</div>
          <h3 className="rec__prompt-title">{passage.title}</h3>
          <p className="rec__prompt-text">{passage.text}</p>
        </section>
      ) : (
        <p className="rec__noprompt">Choose a baseline in step 2 to see the passage it describes, then read that passage at your normal pace.</p>
      )}

      <div className={`rec__deck ${recording ? 'is-live' : ''}`}>
        <svg className="rec__scope" viewBox={`0 0 ${HISTORY} 40`} preserveAspectRatio="none" role="img" aria-label="Recent input level">
          {[10, 20, 30].map((y) => <line key={y} x1={0} x2={HISTORY} y1={y} y2={y} />)}
          {recent.map((peak, i) => {
            const h = Math.max(0.5, levelFraction(peak) * 38);
            return <rect key={i} className={peak >= 0.99 ? 'is-clip' : ''} x={HISTORY - recent.length + i} y={20 - h / 2} width={0.8} height={h} />;
          })}
        </svg>
        <div className="rec__readout">
          <span className="rec__time num" aria-hidden="true">{fmtClock(recording ? latest.current.elapsedS : 0)}</span>
          {recording ? <span className="rec__live"><i aria-hidden="true" /> Recording</span> : null}
          <span className="rec__meter" role="meter" aria-label="Input level" aria-valuemin={FLOOR_DB} aria-valuemax={0} aria-valuenow={Math.round(20 * Math.log10(Math.max(holdPeak, 1e-5)))}>
            <i style={{ width: `${levelFraction(holdPeak) * 100}%` }} className={holdPeak >= 0.99 ? 'is-clip' : ''} />
          </span>
        </div>
        <div className="rec__controls">
          {recording ? (
            <Button variant="primary" icon="stop" onClick={() => void finish()}>Stop</Button>
          ) : (
            <Button variant="primary" icon="mic" busy={phase === 'starting' || phase === 'finishing'} disabled={disabled || phase === 'starting' || phase === 'finishing'} onClick={() => void start()}>
              {phase === 'ready' ? 'Record again' : phase === 'finishing' ? 'Preparing…' : 'Start recording'}
            </Button>
          )}
          {devices.length > 1 ? (
            <label className="rec__device">
              <span className="sr-only">Microphone</span>
              <select className="select" value={deviceId} onChange={(e) => setDeviceId(e.target.value)} disabled={recording} aria-label="Microphone">
                <option value="">Default microphone</option>
                {devices.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
              </select>
            </label>
          ) : null}
        </div>
      </div>

      <p className="rec__status sr-only" role="status" aria-live="polite">
        {phase === 'recording' ? 'Recording started.' : phase === 'finishing' ? 'Preparing the recording.' : phase === 'ready' && take ? `Recording ready, ${Math.round(take.durationS)} seconds.` : ''}
      </p>

      {error ? <p className="form-error" role="alert"><Icon name="alert-circle" size={15} /> {error}</p> : null}
      {processed ? (
        <p className="form-warn"><Chip tone="warn" icon="alert-triangle">Voice processing is on</Chip> This browser kept echo cancellation, noise suppression or automatic gain switched on. They can change loudness and pauses; use another browser or upload a file recorded without them.</p>
      ) : null}
      {recording && capture ? <p className="rec__hint muted">{capture.label} · the browser’s voice processing is switched off so the recording stays as spoken. Keep the bar clear of the right-hand end.</p> : null}

      {take && phase === 'ready' ? (
        <div className="rec__take">
          <div className="rec__take-head">
            <Icon name="file-audio" size={20} />
            <div className="rec__take-meta">
              <div className="rec__take-name truncate" title={take.file.name}>{take.file.name}</div>
              <div className="muted num">{fmtClock(take.durationS)} · {fmtBytes(take.file.size)} · 16 kHz mono WAV</div>
            </div>
          </div>
          <PreviewPlayer file={take.file} />
          {take.peak >= 0.99 ? <p className="form-warn"><Chip tone="warn" icon="alert-triangle">Clipped</Chip> The loudest moments reached full scale, which flattens the signal. Move back from the microphone or lower its input gain, then record again.</p> : null}
          <div className="rec__take-actions">
            <Button variant="primary" icon="check" onClick={() => onUse(take.file)}>Use this recording</Button>
            <Button variant="ghost" icon="trash" onClick={() => { setTake(null); setPhase('idle'); }}>Discard</Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
