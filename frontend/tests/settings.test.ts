import { describe, expect, it } from 'vitest';
import { DEFAULT_SETTINGS, makeTimecode, parseSettings, resolveTheme } from '@/lib/settings';

describe('parseSettings', () => {
  it('returns the defaults for nothing or garbage', () => {
    expect(parseSettings(null)).toEqual(DEFAULT_SETTINGS);
    expect(parseSettings('not json')).toEqual(DEFAULT_SETTINGS);
    expect(parseSettings('42')).toEqual(DEFAULT_SETTINGS);
  });
  it('keeps valid values and replaces invalid ones individually', () => {
    const s = parseSettings(JSON.stringify({ theme: 'dark', density: 'huge', motion: 'reduce', timecode: 'seconds', sidebarCollapsed: 'yes' }));
    expect(s.theme).toBe('dark');
    expect(s.density).toBe(DEFAULT_SETTINGS.density);
    expect(s.motion).toBe('reduce');
    expect(s.timecode).toBe('seconds');
    expect(s.sidebarCollapsed).toBe(DEFAULT_SETTINGS.sidebarCollapsed);
  });
  it('trims the API address and its trailing slashes', () => {
    expect(parseSettings(JSON.stringify({ apiBase: '  http://localhost:8000//  ' })).apiBase).toBe('http://localhost:8000');
    expect(parseSettings(JSON.stringify({ apiBase: 5 })).apiBase).toBe('');
  });
  it('merges lane visibility with the defaults', () => {
    const s = parseSettings(JSON.stringify({ lanes: { pitch: false, rate: 'no' } }));
    expect(s.lanes).toEqual({ words: true, loudness: true, pitch: false, rate: true, pauses: true });
  });
  it('reads the playhead and ground-truth switches', () => {
    const s = parseSettings(JSON.stringify({ followPlayhead: false, showGroundTruth: false }));
    expect(s.followPlayhead).toBe(false);
    expect(s.showGroundTruth).toBe(false);
  });
});

describe('theme and time format', () => {
  it('resolves the system theme', () => {
    expect(resolveTheme('system', true)).toBe('dark');
    expect(resolveTheme('system', false)).toBe('light');
    expect(resolveTheme('light', true)).toBe('light');
  });
  it('writes times as a clock or as seconds', () => {
    const clock = makeTimecode('clock');
    const seconds = makeTimecode('seconds');
    expect(clock.at(65.3)).toBe('1:05.3');
    expect(clock.range(5, 65.34)).toBe('0:05.0–1:05.3');
    expect(seconds.at(65.3)).toBe('65.3 s');
    expect(seconds.range(5, 65.34)).toBe('5.0–65.3 s');
  });
});
