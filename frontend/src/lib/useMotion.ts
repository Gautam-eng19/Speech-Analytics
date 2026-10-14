import { useEffect, useState } from 'react';
import { useSettings } from './settings';

const query = (q: string): MediaQueryList | null => (typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(q) : null);

/** Follows a media query for as long as the component is mounted. */
function useMedia(q: string, fallback: boolean): boolean {
  const [matches, setMatches] = useState(() => query(q)?.matches ?? fallback);
  useEffect(() => {
    const media = query(q);
    if (!media) return;
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener?.('change', update);
    return () => media.removeEventListener?.('change', update);
  }, [q]);
  return matches;
}

/** True when decorative motion is allowed: neither the operating system nor the Settings page asks for reduced motion. */
export function useMotionAllowed(): boolean {
  const preference = useSettings().motion;
  const systemReduces = useMedia('(prefers-reduced-motion: reduce)', false);
  return preference !== 'reduce' && !systemReduces;
}

/** True on a device whose main pointer is a finger: no hover, no precise position. Pointer-reactive decoration is skipped there. */
export function useCoarsePointer(): boolean {
  return useMedia('(pointer: coarse)', false);
}
