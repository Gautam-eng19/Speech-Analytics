import { useEffect, useState } from 'react';
import { fetchSampleResult, SAMPLES_BASE } from '@/api/client';
import type { AnalysisResult, SampleEntry } from '@/api/types';
import { loadSamples } from '@/state/analysis';

/** The demo sample the landing page draws: one real result of the real pipeline on a synthetic voice, plus its audio. */
export interface DemoSample {
  entry: SampleEntry;
  result: AnalysisResult;
  audioUrl: string;
}

/** The sample with the most varied findings is the most useful picture; fall back to any sample that has one, then to the first. */
export const PREFERRED_SAMPLE = 'mixed-flaws';

let pending: Promise<DemoSample | null> | null = null;

export function loadDemoSample(): Promise<DemoSample | null> {
  if (!pending) {
    pending = (async () => {
      try {
        const index = await loadSamples();
        const entry = index.samples.find((s) => s.id === PREFERRED_SAMPLE) ?? index.samples.find((s) => s.injected.length > 0) ?? index.samples[0];
        if (!entry) return null;
        const result = await fetchSampleResult(entry.result);
        return { entry, result, audioUrl: `${SAMPLES_BASE}/${entry.audio}` };
      } catch {
        return null;
      }
    })().then((sample) => {
      if (!sample) pending = null; // try again on the next visit rather than remembering a failure
      return sample;
    });
  }
  return pending;
}

export type DemoState = { status: 'loading'; sample: null } | { status: 'ready'; sample: DemoSample } | { status: 'unavailable'; sample: null };

export function useDemoSample(): DemoState {
  const [state, setState] = useState<DemoState>({ status: 'loading', sample: null });
  useEffect(() => {
    let cancelled = false;
    void loadDemoSample().then((sample) => {
      if (!cancelled) setState(sample ? { status: 'ready', sample } : { status: 'unavailable', sample: null });
    });
    return () => { cancelled = true; };
  }, []);
  return state;
}
