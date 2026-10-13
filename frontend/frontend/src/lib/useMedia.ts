import { useSyncExternalStore } from 'react';

/** True while the media query matches (e.g. '(min-width: 1101px)'). Subscribes to changes. */
export function useMedia(query: string): boolean {
  const subscribe = (notify: () => void) => {
    if (typeof window.matchMedia !== 'function') return () => undefined;
    const list = window.matchMedia(query);
    list.addEventListener('change', notify);
    return () => list.removeEventListener('change', notify);
  };
  const snapshot = () => (typeof window.matchMedia === 'function' ? window.matchMedia(query).matches : true);
  return useSyncExternalStore(subscribe, snapshot, () => true);
}
