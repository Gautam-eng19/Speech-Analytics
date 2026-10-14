import { describe, expect, it } from 'vitest';
import { resample, resampleAsync } from '@/recording/resample';
import { encodeWav16 } from '@/recording/wav';

const tone = (hz: number, seconds: number, rate: number, amplitude = 0.5) =>
  Float32Array.from({ length: Math.round(seconds * rate) }, (_, i) => amplitude * Math.sin((2 * Math.PI * hz * i) / rate));
const rms = (x: Float32Array, from = 0, to = x.length) => Math.sqrt(x.slice(from, to).reduce((s, v) => s + v * v, 0) / Math.max(1, to - from));
const text = (bytes: Uint8Array, at: number, length: number) => String.fromCharCode(...bytes.slice(at, at + length));

describe('encodeWav16', () => {
  it('writes a canonical mono 16-bit PCM header', () => {
    const wav = encodeWav16(new Float32Array(160), 16000);
    const view = new DataView(wav.buffer);
    expect(text(wav, 0, 4)).toBe('RIFF');
    expect(text(wav, 8, 4)).toBe('WAVE');
    expect(text(wav, 12, 4)).toBe('fmt ');
    expect(text(wav, 36, 4)).toBe('data');
    expect(view.getUint32(4, true)).toBe(wav.length - 8);
    expect(view.getUint16(20, true)).toBe(1); // PCM
    expect(view.getUint16(22, true)).toBe(1); // mono
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getUint32(28, true)).toBe(32000);
    expect(view.getUint16(34, true)).toBe(16);
    expect(view.getUint32(40, true)).toBe(320);
    expect(wav.length).toBe(44 + 320);
  });
  it('converts samples with the full 16-bit range and clamps anything beyond it', () => {
    const wav = encodeWav16(Float32Array.of(0, 1, -1, 2, -2, 0.5, Number.NaN), 16000);
    const view = new DataView(wav.buffer);
    const at = (i: number) => view.getInt16(44 + i * 2, true);
    expect([at(0), at(1), at(2), at(3), at(4)]).toEqual([0, 32767, -32768, 32767, -32768]);
    expect(at(5)).toBe(16384);
    expect(at(6)).toBe(0);
  });
  it('is deterministic', () => {
    const x = tone(440, 0.1, 16000);
    expect(encodeWav16(x, 16000)).toEqual(encodeWav16(x, 16000));
  });
});

describe('resample', () => {
  it('returns a copy when the rates are equal', () => {
    const x = tone(440, 0.05, 16000);
    const y = resample(x, 16000, 16000);
    expect(y).toEqual(x);
    expect(y).not.toBe(x);
  });
  it('gives the right length', () => {
    expect(resample(new Float32Array(48000), 48000, 16000).length).toBe(16000);
    expect(resample(new Float32Array(44100), 44100, 16000).length).toBe(16000);
    expect(resample(new Float32Array(8000), 8000, 16000).length).toBe(16000);
  });
  it('drops a trailing partial output sample instead of inventing one', () => {
    // 10 samples at 48 kHz span 3.33 output samples at 16 kHz: three complete ones fit.
    expect(resample(new Float32Array(10), 48000, 16000).length).toBe(3);
    expect(resample(new Float32Array(11), 48000, 16000).length).toBe(3);
    expect(resample(new Float32Array(12), 48000, 16000).length).toBe(4);
  });
  it('keeps a tone below the new Nyquist frequency at its level and frequency', () => {
    const y = resample(tone(1000, 1, 48000), 48000, 16000);
    expect(rms(y, 2000, 14000)).toBeCloseTo(0.5 / Math.SQRT2, 2);
    let crossings = 0;
    for (let i = 2001; i < 14000; i++) if (y[i - 1]! < 0 && y[i]! >= 0) crossings++;
    expect(crossings).toBeCloseTo((12000 / 16000) * 1000, -1);
  });
  it('removes what the new rate cannot represent instead of folding it back', () => {
    const y = resample(tone(12000, 1, 48000), 48000, 16000);
    expect(rms(y, 2000, 14000)).toBeLessThan(0.01);
  });
  it('also converts between rates that are not a whole ratio', () => {
    const y = resample(tone(1000, 1, 44100), 44100, 16000);
    expect(rms(y, 2000, 14000)).toBeCloseTo(0.5 / Math.SQRT2, 2);
  });
  it('keeps the level of a constant signal, including at the edges', () => {
    const y = resample(new Float32Array(4800).fill(0.25), 48000, 16000);
    expect(y[0]).toBeCloseTo(0.25, 5);
    expect(y[y.length - 1]).toBeCloseTo(0.25, 5);
  });
  it('gives the same samples every time, and the same from the sliced version', async () => {
    const x = tone(700, 0.5, 48000);
    const a = resample(x, 48000, 16000);
    expect(resample(x, 48000, 16000)).toEqual(a);
    expect(await resampleAsync(x, 48000, 16000, 1000)).toEqual(a);
  });
  it('gives the sliced version the same length, including when the last output sample is incomplete', async () => {
    for (const n of [10, 11, 12, 24001, 24002]) {
      const sync = resample(new Float32Array(n), 48000, 16000);
      const sliced = await resampleAsync(new Float32Array(n), 48000, 16000, 5);
      expect(sliced.length).toBe(sync.length);
      expect(sliced.length).toBe(Math.floor(n / 3));
    }
  });
});
