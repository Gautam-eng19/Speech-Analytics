import { createStore, useStore } from '@/lib/store';

/**
 * Audio playback. One HTMLAudioElement drives everything; the playhead is a separate store updated every animation frame while
 * playing, so only the components that draw the playhead re-render at that rate.
 *
 * Times are seconds on the uploaded file's own timeline, which is also the timeline the API reports (source time).
 */
export interface PlayerState {
  src: string | null;
  ready: boolean;
  playing: boolean;
  duration: number;
  rate: number;
  /** A range being played: stops at `end`, or jumps back to `start` when `loop` is set. */
  range: { start: number; end: number; loop: boolean } | null;
  error: string | null;
}

const INITIAL: PlayerState = { src: null, ready: false, playing: false, duration: 0, rate: 1, range: null, error: null };

export const playerStore = createStore<PlayerState>(INITIAL);
export const playheadStore = createStore<number>(0);

let audio: HTMLAudioElement | null = null;
let frame = 0;

function element(): HTMLAudioElement {
  if (audio) return audio;
  audio = new Audio();
  audio.preload = 'auto';
  audio.addEventListener('loadedmetadata', () => playerStore.set((s) => ({ ...s, ready: true, duration: audio?.duration ?? 0, error: null })));
  audio.addEventListener('error', () => playerStore.set((s) => ({ ...s, ready: false, playing: false, error: 'The audio could not be played in this browser.' })));
  audio.addEventListener('ended', () => {
    playerStore.set((s) => ({ ...s, playing: false, range: null }));
    stopLoop();
  });
  audio.addEventListener('pause', () => {
    playerStore.set((s) => ({ ...s, playing: false }));
    stopLoop();
    playheadStore.set(audio?.currentTime ?? 0);
  });
  audio.addEventListener('play', () => {
    playerStore.set((s) => ({ ...s, playing: true }));
    startLoop();
  });
  audio.addEventListener('seeked', () => playheadStore.set(audio?.currentTime ?? 0));
  return audio;
}

function tick(): void {
  const a = element();
  const t = a.currentTime;
  const { range } = playerStore.get();
  if (range && t >= range.end) {
    if (range.loop) a.currentTime = range.start;
    else {
      a.pause();
      playerStore.set((s) => ({ ...s, range: null }));
      return;
    }
  }
  playheadStore.set(a.currentTime);
  frame = requestAnimationFrame(tick);
}

function startLoop(): void {
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(tick);
}

function stopLoop(): void {
  cancelAnimationFrame(frame);
}

/** Load a new source (or none). Resets the playhead. */
export function loadAudio(src: string | null): void {
  const a = element();
  a.pause();
  stopLoop();
  playheadStore.set(0);
  if (src === null) {
    a.removeAttribute('src');
    a.load();
    playerStore.set({ ...INITIAL });
    return;
  }
  playerStore.set({ ...INITIAL, src, rate: playerStore.get().rate });
  a.src = src;
  a.playbackRate = playerStore.get().rate;
  a.load();
}

export async function play(): Promise<void> {
  const a = element();
  if (!a.src) return;
  try {
    await a.play();
  } catch {
    playerStore.set((s) => ({ ...s, playing: false, error: 'Playback was blocked by the browser. Press play again.' }));
  }
}

export function pause(): void {
  element().pause();
}

export function toggle(): void {
  if (playerStore.get().playing) pause();
  else void play();
}

export function seek(seconds: number): void {
  const a = element();
  const { duration } = playerStore.get();
  const t = Math.min(Math.max(0, seconds), duration > 0 ? duration : seconds);
  a.currentTime = t;
  playheadStore.set(t);
}

export function seekBy(delta: number): void {
  seek(element().currentTime + delta);
}

export function setRate(rate: number): void {
  const a = element();
  a.playbackRate = rate;
  playerStore.set((s) => ({ ...s, rate }));
}

/** Play [start, end] once, or in a loop. */
export function playRange(start: number, end: number, loop = false): void {
  playerStore.set((s) => ({ ...s, range: { start, end, loop } }));
  seek(start);
  void play();
}

export function clearRange(): void {
  playerStore.set((s) => ({ ...s, range: null }));
}

export const usePlayer = (): PlayerState => useStore(playerStore, (s) => s);
export const usePlayhead = (): number => useStore(playheadStore, (t) => t);
export const useIsPlaying = (): boolean => useStore(playerStore, (s) => s.playing);
export const hasAudio = (): boolean => playerStore.get().src !== null && playerStore.get().ready;
