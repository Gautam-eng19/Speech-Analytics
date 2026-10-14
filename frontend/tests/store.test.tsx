import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { createStore, safeStorage, useStore } from '@/lib/store';

describe('createStore', () => {
  it('holds state and notifies subscribers on change', () => {
    const store = createStore(1);
    const listener = vi.fn();
    const off = store.subscribe(listener);
    store.set(2);
    store.set((n) => n + 1);
    expect(store.get()).toBe(3);
    expect(listener).toHaveBeenCalledTimes(2);
    off();
    store.set(9);
    expect(listener).toHaveBeenCalledTimes(2);
  });
  it('does not notify when the value is unchanged', () => {
    const store = createStore({ a: 1 });
    const listener = vi.fn();
    store.subscribe(listener);
    const same = store.get();
    store.set(same);
    expect(listener).not.toHaveBeenCalled();
  });
});

describe('useStore', () => {
  it('re-renders only when the selected slice changes', () => {
    const store = createStore({ a: 1, b: 1 });
    let renders = 0;
    const { result } = renderHook(() => {
      renders += 1;
      return useStore(store, (s) => s.a);
    });
    expect(result.current).toBe(1);
    const before = renders;
    act(() => store.set((s) => ({ ...s, b: 2 })));
    expect(renders).toBe(before);
    act(() => store.set((s) => ({ ...s, a: 5 })));
    expect(result.current).toBe(5);
  });
  it('lets a selector build objects without looping', () => {
    const store = createStore([1, 2, 3]);
    const { result } = renderHook(() => useStore(store, (list) => ({ count: list.length })));
    expect(result.current.count).toBe(3);
    act(() => store.set([1]));
    expect(result.current.count).toBe(1);
  });
});

describe('safeStorage', () => {
  it('round-trips values', () => {
    expect(safeStorage.set('k', 'v')).toBe(true);
    expect(safeStorage.get('k')).toBe('v');
    safeStorage.remove('k');
    expect(safeStorage.get('k')).toBeNull();
  });
  it('never throws when storage is blocked', () => {
    const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota'); });
    expect(safeStorage.get('k')).toBeNull();
    expect(safeStorage.set('k', 'v')).toBe(false);
    get.mockRestore();
    set.mockRestore();
  });
});
