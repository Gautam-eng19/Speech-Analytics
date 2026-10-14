import { useMemo } from 'react';
import { fmtClock, fmtNum } from './format';
import { createStore, safeStorage, useStore } from './store';

export type ThemePref = 'system' | 'light' | 'dark';
export type Density = 'comfortable' | 'compact';
export type MotionPref = 'system' | 'reduce';
export type TimecodeFormat = 'clock' | 'seconds';
/** Lanes of the timeline that can be switched on and off (the finding lane and the time axis are always shown). */
export type LaneToggle = 'words' | 'loudness' | 'pitch' | 'rate' | 'pauses';
export const LANE_TOGGLES: readonly LaneToggle[] = ['words', 'loudness', 'pitch', 'rate', 'pauses'];

export interface Settings {
  theme: ThemePref;
  density: Density;
  motion: MotionPref;
  timecode: TimecodeFormat;
  sidebarCollapsed: boolean;
  /** Base URL of the API. Empty = same origin (the normal case: the API serves this dashboard, or Vite proxies /api). */
  apiBase: string;
  /** Draw the injected ground truth on samples that have it. */
  showGroundTruth: boolean;
  lanes: Record<LaneToggle, boolean>;
  /** Scroll the timeline with the playhead during playback. */
  followPlayhead: boolean;
}

export const DEFAULT_SETTINGS: Settings = {
  theme: 'dark',
  density: 'comfortable',
  motion: 'system',
  timecode: 'clock',
  sidebarCollapsed: false,
  apiBase: '',
  showGroundTruth: true,
  lanes: { words: true, loudness: true, pitch: true, rate: true, pauses: true },
  followPlayhead: true,
};

export const SETTINGS_KEY = 'sa.settings.v1';

export function parseSettings(raw: string | null): Settings {
  if (!raw) return { ...DEFAULT_SETTINGS };
  try {
    const data = JSON.parse(raw) as Partial<Settings>;
    const pick = <K extends keyof Settings>(key: K, allowed?: readonly Settings[K][]): Settings[K] => {
      const value = data[key];
      if (value === undefined || (allowed && !allowed.includes(value as Settings[K]))) return DEFAULT_SETTINGS[key];
      return value as Settings[K];
    };
    return {
      theme: pick('theme', ['system', 'light', 'dark']),
      density: pick('density', ['comfortable', 'compact']),
      motion: pick('motion', ['system', 'reduce']),
      timecode: pick('timecode', ['clock', 'seconds']),
      sidebarCollapsed: typeof data.sidebarCollapsed === 'boolean' ? data.sidebarCollapsed : DEFAULT_SETTINGS.sidebarCollapsed,
      apiBase: typeof data.apiBase === 'string' ? data.apiBase.trim().replace(/\/+$/, '') : DEFAULT_SETTINGS.apiBase,
      showGroundTruth: typeof data.showGroundTruth === 'boolean' ? data.showGroundTruth : DEFAULT_SETTINGS.showGroundTruth,
      lanes: Object.fromEntries(
        LANE_TOGGLES.map((lane) => [lane, typeof data.lanes?.[lane] === 'boolean' ? data.lanes[lane] : DEFAULT_SETTINGS.lanes[lane]]),
      ) as Record<LaneToggle, boolean>,
      followPlayhead: typeof data.followPlayhead === 'boolean' ? data.followPlayhead : DEFAULT_SETTINGS.followPlayhead,
    };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

export const settingsStore = createStore<Settings>(parseSettings(safeStorage.get(SETTINGS_KEY)));

export function updateSettings(patch: Partial<Settings>): void {
  settingsStore.set((previous) => ({ ...previous, ...patch }));
}

export function useSettings(): Settings {
  return useStore(settingsStore, (s) => s);
}

export function resolveTheme(pref: ThemePref, systemDark: boolean): 'light' | 'dark' {
  return pref === 'system' ? (systemDark ? 'dark' : 'light') : pref;
}

/** Keep <html data-theme/data-density/data-motion> and localStorage in step with the settings. Call once at start-up. */
export function bindSettingsToDocument(): () => void {
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  const apply = () => {
    const s = settingsStore.get();
    const root = document.documentElement;
    root.dataset.theme = resolveTheme(s.theme, media.matches);
    root.dataset.density = s.density;
    if (s.motion === 'reduce') root.dataset.motion = 'reduce';
    else delete root.dataset.motion;
  };
  apply();
  const unsubscribe = settingsStore.subscribe(() => {
    apply();
    safeStorage.set(SETTINGS_KEY, JSON.stringify(settingsStore.get()));
  });
  media.addEventListener('change', apply);
  return () => {
    unsubscribe();
    media.removeEventListener('change', apply);
  };
}

/** Time formatting that follows the "timecode" setting: 1:05.3 or 65.3 s. */
export interface Timecode {
  at(seconds: number, decimals?: number): string;
  range(start: number, end: number, decimals?: number): string;
}

export function makeTimecode(mode: TimecodeFormat): Timecode {
  if (mode === 'seconds') {
    return {
      at: (seconds, decimals = 1) => `${fmtNum(seconds, decimals)} s`,
      range: (start, end, decimals = 1) => `${fmtNum(start, decimals)}–${fmtNum(end, decimals)} s`,
    };
  }
  return {
    at: (seconds, decimals = 1) => fmtClock(seconds, decimals),
    range: (start, end, decimals = 1) => `${fmtClock(start, decimals)}–${fmtClock(end, decimals)}`,
  };
}

export function useTimecode(): Timecode {
  const mode = useStore(settingsStore, (s) => s.timecode);
  return useMemo(() => makeTimecode(mode), [mode]);
}
