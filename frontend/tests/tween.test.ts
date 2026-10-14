import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { easeOutCubic, useTweened } from '@/charts/useTweened';

describe('easeOutCubic', () => {
  it('starts at 0, ends at 1, never goes backwards, and is quick at the start and slow at the end', () => {
    expect(easeOutCubic(0)).toBe(0);
    expect(easeOutCubic(1)).toBe(1);
    let last = 0;
    for (let i = 1; i <= 20; i++) {
      const v = easeOutCubic(i / 20);
      expect(v).toBeGreaterThanOrEqual(last);
      last = v;
    }
    expect(easeOutCubic(0.5)).toBeGreaterThan(0.5);
  });
});

describe('useTweened', () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance'] }); });
  afterEach(() => { vi.useRealTimers(); });

  it('returns the targets at once when it is not enabled', () => {
    const { result } = renderHook(() => useTweened([10, 50, 90], { enabled: false }));
    expect(result.current).toEqual([10, 50, 90]);
  });

  it('starts at zero and arrives exactly at the targets, then stops', () => {
    const { result } = renderHook(() => useTweened([10, 50, 90], { duration: 500 }));
    expect(result.current).toEqual([0, 0, 0]);
    act(() => { vi.advanceTimersByTime(250); });
    expect(result.current[2]).toBeGreaterThan(0);
    expect(result.current[2]).toBeLessThan(90);
    act(() => { vi.advanceTimersByTime(400); });
    expect(result.current).toEqual([10, 50, 90]);
    const settled = result.current;
    act(() => { vi.advanceTimersByTime(1000); });
    expect(result.current).toBe(settled);
  });

  it('moves on from where it is when the targets change mid-way, without jumping back', () => {
    const { result, rerender } = renderHook(({ t }) => useTweened(t, { duration: 500 }), { initialProps: { t: [100] } });
    act(() => { vi.advanceTimersByTime(250); });
    const before = result.current[0]!;
    rerender({ t: [20] });
    act(() => { vi.advanceTimersByTime(16); });
    expect(Math.abs(result.current[0]! - before)).toBeLessThan(40);
    act(() => { vi.advanceTimersByTime(700); });
    expect(result.current).toEqual([20]);
  });

  it('copes with a different number of values', () => {
    const { result, rerender } = renderHook(({ t }) => useTweened(t, { duration: 100 }), { initialProps: { t: [1, 2] } });
    act(() => { vi.advanceTimersByTime(300); });
    rerender({ t: [1, 2, 3, 4] });
    act(() => { vi.advanceTimersByTime(300); });
    expect(result.current).toEqual([1, 2, 3, 4]);
    rerender({ t: [] });
    act(() => { vi.advanceTimersByTime(300); });
    expect(result.current).toEqual([]);
  });
});
