import { createStore, safeStorage, useStore } from '@/lib/store';
import type { AnalysisResult, AnalysisSource } from '@/api/types';

/**
 * Recent analyses, kept in this browser only. An entry stores a small snapshot for the list (title, score, counts) and the analysis
 * id. The result itself is always fetched again (from the API, or from the sample files), so the backend stays the source of truth.
 * Audio of uploads is NOT kept: re-opening an upload shows the analysis without playback.
 */
export interface HistoryEntry {
  id: string;
  title: string;
  source: AnalysisSource;
  /** For samples: the sample id, so it can be reopened without the API. */
  sampleId?: string;
  openedAt: number;
  composite: number;
  flawCount: number;
  durationS: number;
  baselineId: string;
  passageId: string;
}

const KEY = 'sa.history.v1';
const MAX = 40;

function load(): HistoryEntry[] {
  const raw = safeStorage.get(KEY);
  if (!raw) return [];
  try {
    const data = JSON.parse(raw) as unknown;
    if (!Array.isArray(data)) return [];
    return data.filter(
      (e): e is HistoryEntry =>
        !!e && typeof e === 'object' && typeof (e as HistoryEntry).id === 'string' && typeof (e as HistoryEntry).title === 'string' &&
        typeof (e as HistoryEntry).openedAt === 'number',
    );
  } catch {
    return [];
  }
}

export const historyStore = createStore<HistoryEntry[]>(load());

historyStore.subscribe(() => safeStorage.set(KEY, JSON.stringify(historyStore.get())));

export function recordHistory(result: AnalysisResult, title: string, source: AnalysisSource, sampleId?: string): void {
  const entry: HistoryEntry = {
    id: result.analysis_id,
    title,
    source,
    sampleId,
    openedAt: Date.now(),
    composite: result.scores.composite_score,
    flawCount: result.flaws.length,
    durationS: result.audio.source_duration_s ?? result.audio.duration_s,
    baselineId: result.baseline.baseline_id,
    passageId: result.baseline.passage_id,
  };
  historyStore.set((list) => [entry, ...list.filter((e) => e.id !== entry.id)].slice(0, MAX));
}

export function removeHistory(id: string): void {
  historyStore.set((list) => list.filter((e) => e.id !== id));
}

export function clearHistory(): void {
  historyStore.set([]);
}

export const useHistory = (): HistoryEntry[] => useStore(historyStore, (s) => s);
