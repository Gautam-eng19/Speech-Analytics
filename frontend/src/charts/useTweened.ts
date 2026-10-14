import { useEffect, useRef, useState } from 'react';

export const easeOutCubic = (t: number): number => 1 - (1 - t) ** 3;

/**
 * Numbers that glide to their targets: from zero the first time they are shown, from wherever they are when the targets change.
 * It is a finite animation (a few dozen renders, then it stops), never a loop. With `enabled` false the targets are returned as they are.
 */
export function useTweened(targets: readonly number[], { enabled = true, duration = 720 }: { enabled?: boolean; duration?: number } = {}): number[] {
  const key = targets.join('|');
  const [shown, setShown] = useState<number[]>(() => (enabled && duration > 0 ? targets.map(() => 0) : [...targets]));
  const current = useRef(shown);

  useEffect(() => {
    const goal = key === '' ? [] : key.split('|').map(Number);
    if (!enabled || duration <= 0) {
      current.current = goal;
      setShown(goal);
      return;
    }
    const begin = goal.map((_, i) => current.current[i] ?? 0);
    const t0 = performance.now();
    let frame = 0;
    const step = (now: number) => {
      const progress = Math.min(1, Math.max(0, (now - t0) / duration));
      const k = easeOutCubic(progress);
      const next = goal.map((g, i) => (begin[i] as number) + (g - (begin[i] as number)) * k);
      current.current = next;
      setShown(next);
      if (progress < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [key, enabled, duration]);

  return shown;
}
