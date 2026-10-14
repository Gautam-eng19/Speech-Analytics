import { useEffect, useRef, useState } from 'react';
import { Icon } from '@/components/Icon';
import { fmtClock } from '@/lib/format';

/** A small player for the chosen file, separate from the analysis player so choosing a file never disturbs an open analysis. */
export function PreviewPlayer({ file, onDuration }: { file: File; onDuration?: (seconds: number) => void }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [state, setState] = useState({ playing: false, time: 0, duration: 0, failed: false });

  useEffect(() => {
    const url = URL.createObjectURL(file);
    const element = new Audio();
    audio.current = element;
    element.preload = 'metadata';
    element.src = url;
    const onMeta = () => {
      setState((s) => ({ ...s, duration: Number.isFinite(element.duration) ? element.duration : 0, failed: false }));
      if (Number.isFinite(element.duration)) onDuration?.(element.duration);
    };
    const onTime = () => setState((s) => ({ ...s, time: element.currentTime }));
    const onPlay = () => setState((s) => ({ ...s, playing: true }));
    const onPause = () => setState((s) => ({ ...s, playing: false }));
    const onError = () => setState((s) => ({ ...s, failed: true, playing: false }));
    element.addEventListener('loadedmetadata', onMeta);
    element.addEventListener('timeupdate', onTime);
    element.addEventListener('play', onPlay);
    element.addEventListener('pause', onPause);
    element.addEventListener('ended', onPause);
    element.addEventListener('error', onError);
    setState({ playing: false, time: 0, duration: 0, failed: false });
    return () => {
      element.pause();
      element.removeAttribute('src');
      element.load();
      URL.revokeObjectURL(url);
      audio.current = null;
    };
    // The callback is only a notification; it must not restart playback when its identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file]);

  const toggle = () => {
    const element = audio.current;
    if (!element) return;
    if (element.paused) void element.play().catch(() => setState((s) => ({ ...s, failed: true })));
    else element.pause();
  };

  if (state.failed) return <p className="preview__error">This browser cannot play the file. It can still be uploaded; the server decodes it itself.</p>;
  return (
    <div className="preview">
      <button type="button" className="preview__play" onClick={toggle} aria-label={state.playing ? 'Pause preview' : 'Play preview'}>
        <Icon name={state.playing ? 'pause' : 'play'} size={15} />
      </button>
      <input
        className="scrubber"
        type="range"
        min={0}
        max={state.duration || 1}
        step={0.01}
        value={Math.min(state.time, state.duration || 1)}
        onChange={(e) => { if (audio.current) audio.current.currentTime = Number(e.target.value); setState((s) => ({ ...s, time: Number(e.target.value) })); }}
        aria-label="Preview position"
        style={{ ['--p' as string]: `${state.duration > 0 ? (state.time / state.duration) * 100 : 0}%` }}
      />
      <span className="preview__time num">{fmtClock(state.time)} / {fmtClock(state.duration)}</span>
    </div>
  );
}
