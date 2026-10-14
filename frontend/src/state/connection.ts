import type { BaselineListResponse, HealthResponse } from '@/api/types';
import { ApiError } from '@/api/client';
import { createStore, useStore } from '@/lib/store';
import { api } from './api';

// ---- API health ----------------------------------------------------------------------------------------------------------
export interface Connection {
  status: 'checking' | 'online' | 'offline';
  health: HealthResponse | null;
  checkedAt: number;
}

export const connectionStore = createStore<Connection>({ status: 'checking', health: null, checkedAt: 0 });
export const useConnection = (): Connection => useStore(connectionStore, (s) => s);

export async function checkConnection(): Promise<void> {
  try {
    const health = await api.health();
    connectionStore.set({ status: 'online', health, checkedAt: Date.now() });
  } catch {
    connectionStore.set((s) => ({ status: 'offline', health: s.health, checkedAt: Date.now() }));
  }
}

/** Check now, then every 30 s and whenever the tab becomes visible again. */
export function startConnectionPolling(): () => void {
  void checkConnection();
  const timer = window.setInterval(() => void checkConnection(), 30_000);
  const onVisible = () => {
    if (document.visibilityState === 'visible') void checkConnection();
  };
  document.addEventListener('visibilitychange', onVisible);
  return () => {
    window.clearInterval(timer);
    document.removeEventListener('visibilitychange', onVisible);
  };
}

// ---- baseline catalogue --------------------------------------------------------------------------------------------------
export interface Catalog {
  status: 'idle' | 'loading' | 'ready' | 'error';
  data: BaselineListResponse | null;
  error: ApiError | null;
}

export const catalogStore = createStore<Catalog>({ status: 'idle', data: null, error: null });
export const useCatalog = (): Catalog => useStore(catalogStore, (s) => s);

export async function refreshCatalog(): Promise<void> {
  catalogStore.set((s) => ({ ...s, status: 'loading', error: null }));
  try {
    const data = await api.baselines();
    catalogStore.set({ status: 'ready', data, error: null });
  } catch (error) {
    catalogStore.set((s) => ({ status: 'error', data: s.data, error: error instanceof ApiError ? error : new ApiError('NETWORK_ERROR', 'The baselines could not be loaded.') }));
  }
}
