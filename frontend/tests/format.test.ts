import { describe, expect, it } from 'vitest';
import { fmtBytes, fmtClock, fmtDuration, fmtLevel, fmtNum, fmtRelative, fmtSigned, plural, shortHash, titleCase } from '@/lib/format';

describe('fmtNum', () => {
  it('rounds to the requested number of decimals', () => {
    expect(fmtNum(3.14159, 2)).toBe('3.14');
    expect(fmtNum(2, 1)).toBe('2.0');
  });
  it('shows a dash for missing or non-finite values', () => {
    expect(fmtNum(null)).toBe('-');
    expect(fmtNum(undefined)).toBe('-');
    expect(fmtNum(Number.NaN)).toBe('-');
    expect(fmtNum(Number.POSITIVE_INFINITY)).toBe('-');
  });
  it('never prints a negative zero', () => {
    expect(fmtNum(-0.04, 1)).toBe('0.0');
    expect(fmtNum(-0, 0)).toBe('0');
  });
});

describe('fmtSigned and fmtLevel', () => {
  it('uses a true minus sign and an explicit plus', () => {
    expect(fmtSigned(-3.24, 1)).toBe('−3.2');
    expect(fmtSigned(3.24, 1)).toBe('+3.2');
  });
  it('prints zero without a sign', () => {
    expect(fmtSigned(0.001, 1)).toBe('0.0');
  });
  it('formats levels in dB with a true minus', () => {
    expect(fmtLevel(-24.196, 1)).toBe('−24.2');
    expect(fmtLevel(-0.01, 1)).toBe('0.0');
    expect(fmtLevel(null)).toBe('-');
  });
});

describe('fmtClock', () => {
  it('zero-pads the seconds', () => {
    expect(fmtClock(0)).toBe('0:00.0');
    expect(fmtClock(5.04)).toBe('0:05.0');
    expect(fmtClock(65.34)).toBe('1:05.3');
  });
  it('supports other precisions', () => {
    expect(fmtClock(5, 0)).toBe('0:05');
    expect(fmtClock(65.345, 2)).toBe('1:05.35');
  });
  it('adds hours past one hour and handles rounding up across a boundary', () => {
    expect(fmtClock(3725.2)).toBe('1:02:05.2');
    expect(fmtClock(59.96)).toBe('1:00.0');
  });
  it('handles negative and invalid input', () => {
    expect(fmtClock(-1.5)).toBe('−0:01.5');
    expect(fmtClock(Number.NaN)).toBe('-');
  });
});

describe('fmtDuration', () => {
  it('uses seconds under a minute and minutes beyond', () => {
    expect(fmtDuration(53.144)).toBe('53.1 s');
    expect(fmtDuration(61)).toBe('1 min 01 s');
    expect(fmtDuration(300)).toBe('5 min 00 s');
  });
  it('never prints 60 seconds', () => {
    expect(fmtDuration(119.6)).toBe('2 min 00 s');
    expect(fmtDuration(59.97)).toBe('1 min 00 s');
  });
});

describe('small helpers', () => {
  it('formats bytes', () => {
    expect(fmtBytes(512)).toBe('512 B');
    expect(fmtBytes(2048)).toBe('2 KB');
    expect(fmtBytes(5.5 * 1024 * 1024)).toBe('5.5 MB');
  });
  it('pluralises', () => {
    expect(plural(1, 'finding')).toBe('1 finding');
    expect(plural(3, 'finding')).toBe('3 findings');
    expect(plural(2, 'entry', 'entries')).toBe('2 entries');
  });
  it('shortens hashes', () => {
    expect(shortHash('abcdef0123456789', 8)).toBe('abcdef01');
    expect(shortHash('abc', 8)).toBe('abc');
    expect(shortHash(null)).toBe('-');
  });
  it('title-cases slugs', () => {
    expect(titleCase('within_phrase')).toBe('Within phrase');
    expect(titleCase('cross-sentence')).toBe('Cross sentence');
  });
  it('describes elapsed time', () => {
    const now = 1_000_000_000_000;
    expect(fmtRelative(now - 5_000, now)).toBe('just now');
    expect(fmtRelative(now - 5 * 60_000, now)).toBe('5 min ago');
    expect(fmtRelative(now - 3 * 3_600_000, now)).toBe('3 h ago');
    expect(fmtRelative(now - 2 * 86_400_000, now)).toBe('2 d ago');
  });
});
