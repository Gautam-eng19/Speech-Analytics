import { ApiError, fetchSampleIndex, fetchSampleResult, SAMPLES_BASE, type AnalyzeParams } from '@/api/client';
import type { AnalysisResult, AnalysisSource, SampleEntry, SampleIndex } from '@/api/types';
import { createStore, useStore } from '@/lib/store';
import { recordingDuration } from '@/lib/result';
import { api } from './api';
import { historyStore, recordHistory } from './history';
import { loadAudio } from './player';
import { selectFlaw, setView } from './ui';

/** The analysis currently open in the dashboard, and how it got there. */
export interface LoadedAnalysis {
  id: string;
  result: AnalysisResult;
  source: AnalysisSource;
  title: string;
  /** URL the audio element plays (an object URL of the uploaded file, or a sample file). Null = no playback available. */
  audioUrl: string | null;
  /** Present for demo samples: the injected ground truth and how the sample was chosen. */
  sample: SampleEntry | null;
  loadedAt: number;
}

export interface Progress {
  phase: 'uploading' | 'analysing' | 'loading';
  loaded: number;
  total: number;
  startedAt: number;
}

export interface AnalysisState {
  status: 'idle' | 'loading' | 'ready' | 'error';
  current: LoadedAnalysis | null;
  progress: Progress | null;
  error: ApiError | null;
}

export const analysisStore = createStore<AnalysisState>({ status: 'idle', current: null, progress: null, error: null });
export const useAnalysis = (): AnalysisState => useStore(analysisStore, (s) => s);
export const useCurrent = (): LoadedAnalysis | null => useStore(analysisStore, (s) => s.current);

let controller: AbortController | null = null;
let objectUrl: string | null = null;
let samplesPromise: Promise<SampleIndex> | null = null;

export function loadSamples(force = false): Promise<SampleIndex> {
  if (!samplesPromise || force) {
    samplesPromise = fetchSampleIndex().catch((error: unknown) => {
      samplesPromise = null;
      throw error;
    });
  }
  return samplesPromise;
}

function begin(phase: Progress['phase']): AbortController {
  controller?.abort();
  controller = new AbortController();
  analysisStore.set((s) => ({ ...s, status: 'loading', error: null, progress: { phase, loaded: 0, total: 0, startedAt: Date.now() } }));
  return controller;
}

/** A request that has been replaced by a newer one must not touch the state any more. */
const superseded = (ctl: AbortController): boolean => controller !== ctl;

function fail(error: unknown, ctl: AbortController): false {
  if (superseded(ctl)) return false;
  const apiError = error instanceof ApiError ? error : new ApiError('NETWORK_ERROR', error instanceof Error ? error.message : 'Unexpected error.');
  if (apiError.code === 'ABORTED') {
    analysisStore.set((s) => ({ ...s, status: s.current ? 'ready' : 'idle', progress: null }));
    return false;
  }
  analysisStore.set((s) => ({ ...s, status: 'error', progress: null, error: apiError }));
  return false;
}

function adopt(loaded: LoadedAnalysis): void {
  if (objectUrl && objectUrl !== loaded.audioUrl) {
    URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
  if (loaded.audioUrl?.startsWith('blob:')) objectUrl = loaded.audioUrl;
  loadAudio(loaded.audioUrl);
  selectFlaw(null);
  setView({ t0: 0, t1: recordingDuration(loaded.result) });
  analysisStore.set({ status: 'ready', current: loaded, progress: null, error: null });
  recordHistory(loaded.result, loaded.title, loaded.source, loaded.sample?.id);
}

/** Upload a recording and run the analysis. Resolves true when a result is open. */
export async function analyzeFile(file: File, params: AnalyzeParams): Promise<boolean> {
  const ctl = begin('uploading');
  try {
    const result = await api.analyze(file, params, {
      signal: ctl.signal,
      onUploadProgress: (loaded, total) => {
        if (superseded(ctl)) return;
        analysisStore.set((s) => ({
          ...s,
          progress: s.progress ? { ...s.progress, phase: loaded >= total ? 'analysing' : 'uploading', loaded, total } : s.progress,
        }));
      },
    });
    if (superseded(ctl) || ctl.signal.aborted) return false;
    adopt({ id: result.analysis_id, result, source: 'upload', title: file.name, audioUrl: URL.createObjectURL(file), sample: null, loadedAt: Date.now() });
    return true;
  } catch (error) {
    return fail(error, ctl);
  }
}

export async function openSample(sampleId: string): Promise<boolean> {
  const ctl = begin('loading');
  try {
    const index = await loadSamples();
    const entry = index.samples.find((s) => s.id === sampleId || s.analysis_id === sampleId);
    if (!entry) throw new ApiError('RESULT_NOT_FOUND', 'That sample does not exist.', 404);
    const result = await fetchSampleResult(entry.result, ctl.signal);
    if (superseded(ctl) || ctl.signal.aborted) return false;
    adopt({ id: result.analysis_id, result, source: 'sample', title: entry.title, audioUrl: `${SAMPLES_BASE}/${entry.audio}`, sample: entry, loadedAt: Date.now() });
    return true;
  } catch (error) {
    return fail(error, ctl);
  }
}

/** Open an analysis by id: a demo sample if the id belongs to one, otherwise the API's stored result. */
export async function openById(id: string): Promise<boolean> {
  if (analysisStore.get().current?.id === id) return true;
  try {
    const index = await loadSamples().catch(() => null);
    if (index?.samples.some((s) => s.id === id || s.analysis_id === id)) return openSample(id);
  } catch {
    /* no samples installed: fall through to the API */
  }
  const ctl = begin('loading');
  try {
    const result = await api.result(id, ctl.signal);
    if (superseded(ctl) || ctl.signal.aborted) return false;
    const remembered = historyStore.get().find((e) => e.id === id);
    adopt({
      id: result.analysis_id, result, source: 'history', title: remembered?.title ?? `Analysis ${id.slice(0, 8)}`,
      audioUrl: null, sample: null, loadedAt: Date.now(),
    });
    return true;
  } catch (error) {
    return fail(error, ctl);
  }
}

export function cancelLoading(): void {
  controller?.abort();
}

export function closeAnalysis(): void {
  controller?.abort();
  loadAudio(null);
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
  selectFlaw(null);
  analysisStore.set({ status: 'idle', current: null, progress: null, error: null });
}

export function dismissError(): void {
  analysisStore.set((s) => ({ ...s, status: s.current ? 'ready' : 'idle', error: null }));
}
