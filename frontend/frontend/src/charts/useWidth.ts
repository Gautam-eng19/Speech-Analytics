import { useLayoutEffect, useRef, useState, type RefObject } from 'react';

export interface Size {
  width: number;
  height: number;
}

/** Size in px of an element, kept current with a ResizeObserver (a no-op where it does not exist, e.g. in tests). */
export function useSize<T extends HTMLElement>(): [RefObject<T | null>, Size] {
  const ref = useRef<T>(null);
  const [size, setSize] = useState<Size>({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const measure = () => {
      const rect = node.getBoundingClientRect();
      const next = { width: Math.round(rect.width), height: Math.round(rect.height) };
      setSize((previous) => (previous.width === next.width && previous.height === next.height ? previous : next));
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, size];
}

/** Width in px of an element. */
export function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const [ref, size] = useSize<T>();
  return [ref, size.width];
}
