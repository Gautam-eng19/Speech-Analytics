import { ApiError, type CustomBaselineParams } from '@/api/client';
import type { CustomBaselineResult } from '@/api/types';
import { createStore, useStore } from '@/lib/store';
import { api } from './api';
import { refreshCatalog } from './connection';

/** Making a baseline from the user's own passage and recordings (API contract 1.3.0). It is slow: each recording is aligned to the text. */
export interface CustomProgress {
  phase: 'uploading' | 'building';
  loaded: number;
  total: number;
  startedAt: number;
}

export interface CustomState {
  status: 'idle' | 'working' | 'ready' | 'error';
  progress: CustomProgress | null;
  result: CustomBaselineResult | null;
  error: ApiError | null;
}

const IDLE: CustomState = { status: 'idle', progress: null, result: null, error: null };
export const customStore = createStore<CustomState>(IDLE);
export const useCustom = (): CustomState => useStore(customStore, (s) => s);

let controller: AbortController | null = null;

const asApiError = (error: unknown): ApiError =>
  error instanceof ApiError ? error : new ApiError('NETWORK_ERROR', error instanceof Error ? error.message : 'Unexpected error.');

/** Send the passage and recordings. Resolves true when a baseline is ready (the catalogue is refreshed so it can be chosen everywhere). */
export async function createCustomBaseline(params: CustomBaselineParams): Promise<boolean> {
  controller?.abort();
  const ctl = new AbortController();
  controller = ctl;
  customStore.set({ status: 'working', progress: { phase: 'uploading', loaded: 0, total: 0, startedAt: Date.now() }, result: null, error: null });
  try {
    const result = await api.createCustomBaseline(params, {
      signal: ctl.signal,
      onUploadProgress: (loaded, total) => {
        if (controller !== ctl) return;
        customStore.set((s) => ({ ...s, progress: s.progress ? { ...s.progress, phase: loaded >= total ? 'building' : 'uploading', loaded, total } : s.progress }));
      },
    });
    if (controller !== ctl || ctl.signal.aborted) return false;
    customStore.set({ status: 'ready', progress: null, result, error: null });
    void refreshCatalog();
    return true;
  } catch (error) {
    if (controller !== ctl) return false;
    const apiError = asApiError(error);
    customStore.set(apiError.code === 'ABORTED' ? IDLE : { status: 'error', progress: null, result: null, error: apiError });
    return false;
  }
}

export function cancelCustom(): void {
  controller?.abort();
}

export function resetCustom(): void {
  controller?.abort();
  controller = null;
  customStore.set(IDLE);
}

/** Delete a custom baseline and its passage. Resolves true on success; the catalogue is refreshed either way. */
export async function deleteCustomBaseline(baselineId: string): Promise<boolean> {
  try {
    await api.deleteCustomBaseline(baselineId);
  } catch (error) {
    const apiError = asApiError(error);
    if (apiError.code !== 'BASELINE_NOT_FOUND') {
      customStore.set((s) => ({ ...s, error: apiError }));
      void refreshCatalog();
      return false;
    }
  }
  customStore.set((s) => (s.result?.baseline_id === baselineId ? IDLE : s));
  void refreshCatalog();
  return true;
}
