import { useRef, useSyncExternalStore } from 'react';

/**
 * A minimal external store. State lives outside React so that high-frequency data (the playhead) and cross-page data (the loaded
 * analysis, settings) can be read from anywhere, and components re-render only for the slice they select.
 */
export interface Store<T> {
  get(): T;
  set(next: T | ((previous: T) => T)): void;
  subscribe(listener: () => void): () => void;
}

export function createStore<T>(initial: T): Store<T> {
  let state = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    set(next) {
      const value = typeof next === 'function' ? (next as (previous: T) => T)(state) : next;
      if (Object.is(value, state)) return;
      state = value;
      listeners.forEach((listener) => listener());
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

/** Subscribe to a slice of a store. The selector result is memoised per state so it may build objects safely. */
export function useStore<T, S>(store: Store<T>, selector: (state: T) => S, equals: (a: S, b: S) => boolean = Object.is): S {
  const cache = useRef<{ state: T; value: S } | null>(null);
  const getSnapshot = (): S => {
    const state = store.get();
    const cached = cache.current;
    if (cached && cached.state === state) return cached.value;
    const value = selector(state);
    if (cached && equals(cached.value, value)) {
      cache.current = { state, value: cached.value };
      return cached.value;
    }
    cache.current = { state, value };
    return value;
  };
  return useSyncExternalStore(store.subscribe, getSnapshot, getSnapshot);
}

/** localStorage that never throws (private windows, blocked storage, quota). */
export const safeStorage = {
  get(key: string): string | null {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key: string, value: string): boolean {
    try {
      window.localStorage.setItem(key, value);
      return true;
    } catch {
      return false;
    }
  },
  remove(key: string): void {
    try {
      window.localStorage.removeItem(key);
    } catch {
      /* storage unavailable: nothing to remove */
    }
  },
};
