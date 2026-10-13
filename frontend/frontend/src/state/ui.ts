import { createStore, useStore } from '@/lib/store';
import type { TimeWindow } from '@/lib/time';

// ---- toasts --------------------------------------------------------------------------------------------------------------
export type ToastKind = 'info' | 'success' | 'error';
export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

export const toastStore = createStore<Toast[]>([]);
let toastSeq = 0;

export function pushToast(message: string, kind: ToastKind = 'info', ttlMs = 4200): number {
  const id = ++toastSeq;
  toastStore.set((list) => [...list.slice(-3), { id, kind, message }]);
  if (ttlMs > 0) window.setTimeout(() => dismissToast(id), ttlMs);
  return id;
}

export function dismissToast(id: number): void {
  toastStore.set((list) => list.filter((t) => t.id !== id));
}

// ---- overlays ------------------------------------------------------------------------------------------------------------
export interface OverlayState {
  palette: boolean;
  shortcuts: boolean;
  mobileNav: boolean;
}

export const overlayStore = createStore<OverlayState>({ palette: false, shortcuts: false, mobileNav: false });

export function setOverlay(patch: Partial<OverlayState>): void {
  overlayStore.set((s) => ({ ...s, ...patch }));
}

export const useOverlays = (): OverlayState => useStore(overlayStore, (s) => s);

// ---- selection and view (shared by the ribbon, the timeline, the flaw list and the transcript) -----------------------------
export interface SelectionState {
  flawId: string | null;
}

export const selectionStore = createStore<SelectionState>({ flawId: null });

export function selectFlaw(flawId: string | null): void {
  selectionStore.set({ flawId });
}

/** The time window shown by the timeline. The delivery ribbon displays and edits the same window. */
export const viewStore = createStore<TimeWindow>({ t0: 0, t1: 1 });

export function setView(window: TimeWindow): void {
  viewStore.set(window);
}

/** Time under the pointer on the timeline (null when the pointer is elsewhere); drives the crosshair on every lane. */
export const hoverStore = createStore<number | null>(null);

// ---- flaw list filter (kept while the user moves between pages) -----------------------------------------------------------------
export interface FlawsFilter {
  /** Flaw types to show; empty means all. */
  types: string[];
  sort: 'time' | 'severity';
}

export const flawsFilterStore = createStore<FlawsFilter>({ types: [], sort: 'time' });

export function setFlawsFilter(patch: Partial<FlawsFilter>): void {
  flawsFilterStore.set((f) => ({ ...f, ...patch }));
}
