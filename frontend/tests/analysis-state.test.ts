import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import { analysisStore, analyzeFile, cancelLoading, closeAnalysis, dismissError, openById, openSample } from '@/state/analysis';
import { clearHistory, historyStore, recordHistory } from '@/state/history';
import { playerStore } from '@/state/player';
import { selectionStore, viewStore } from '@/state/ui';
import { hesitantResult, mixedResult, sampleIndex } from './fixtures';
import { stubFetch } from './helpers';

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

beforeEach(() => { closeAnalysis(); clearHistory(); selectionStore.set({ flawId: null }); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('opening analyses', () => {
  it('opens a demo sample with its audio, ground truth and a full-length view', async () => {
    stubFetch();
    expect(await openSample('hesitant-delivery')).toBe(true);
    const state = analysisStore.get();
    expect(state.status).toBe('ready');
    expect(state.current).toMatchObject({ id: hesitantResult.analysis_id, source: 'sample', title: 'Hesitant delivery' });
    expect(state.current!.sample!.injected.length).toBe(2);
    expect(state.current!.audioUrl).toMatch(/samples\/hesitant-delivery\.wav$/);
    expect(playerStore.get().src).toMatch(/hesitant-delivery\.wav$/);
    expect(viewStore.get()).toEqual({ t0: 0, t1: hesitantResult.audio.source_duration_s });
  });
  it('records every opened analysis in the history list', async () => {
    stubFetch();
    await openSample('hesitant-delivery');
    expect(historyStore.get()).toHaveLength(1);
    expect(historyStore.get()[0]).toMatchObject({ id: hesitantResult.analysis_id, source: 'sample', flawCount: hesitantResult.flaws.length, composite: hesitantResult.scores.composite_score });
  });
  it('recognises a sample by its analysis id and reads anything else from the API', async () => {
    const { calls } = stubFetch({ '/api/v1/result/other-id': () => json({ ...mixedResult, analysis_id: 'other-id' }) });
    expect(await openById(sampleIndex.samples[0]!.analysis_id)).toBe(true);
    expect(analysisStore.get().current!.source).toBe('sample');
    expect(await openById('other-id')).toBe(true);
    expect(analysisStore.get().current).toMatchObject({ id: 'other-id', source: 'history', audioUrl: null });
    expect(calls.some((u) => u.endsWith('/api/v1/result/other-id'))).toBe(true);
    expect(playerStore.get().src).toBeNull();
  });
  it('does nothing when the analysis is already open', async () => {
    const { calls } = stubFetch();
    await openSample('mixed-flaws');
    const before = calls.length;
    expect(await openById(mixedResult.analysis_id)).toBe(true);
    expect(calls.length).toBe(before);
  });
  it('reports a missing analysis as an error the page can explain, and clears it on dismiss', async () => {
    stubFetch();
    expect(await openById('nope')).toBe(false);
    expect(analysisStore.get()).toMatchObject({ status: 'error', current: null });
    expect(analysisStore.get().error).toMatchObject({ code: 'RESULT_NOT_FOUND' });
    dismissError();
    expect(analysisStore.get()).toMatchObject({ status: 'idle', error: null });
  });
  it('keeps the open analysis when a different one fails to load', async () => {
    stubFetch();
    await openSample('mixed-flaws');
    expect(await openById('nope')).toBe(false);
    expect(analysisStore.get().current!.id).toBe(mixedResult.analysis_id);
    dismissError();
    expect(analysisStore.get().status).toBe('ready');
  });
  it('closing resets everything, including playback', async () => {
    stubFetch();
    await openSample('mixed-flaws');
    closeAnalysis();
    expect(analysisStore.get()).toMatchObject({ status: 'idle', current: null });
    expect(playerStore.get().src).toBeNull();
  });
});

describe('overlapping requests', () => {
  /** A fetch whose API responses are released by hand, and which ignores aborts (as a slow network might). */
  function gatedFetch() {
    const gates = new Map<string, (r: Response) => void>();
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => new Promise<Response>((resolve) => {
      const url = String(input);
      if (url.endsWith('/samples/index.json')) return resolve(json(sampleIndex));
      gates.set(url.split('/').pop()!, resolve);
    })));
    return gates;
  }
  const tick = () => new Promise((r) => setTimeout(r, 0));

  it('lets the newest request win even if an older response arrives later', async () => {
    const gates = gatedFetch();
    const first = openById('first');
    await tick();
    const second = openById('second');
    await tick();
    gates.get('second')!(json({ ...hesitantResult, analysis_id: 'second' }));
    expect(await second).toBe(true);
    gates.get('first')!(json({ ...mixedResult, analysis_id: 'first' }));
    expect(await first).toBe(false);
    expect(analysisStore.get().current!.id).toBe('second');
    expect(analysisStore.get().status).toBe('ready');
  });
  it('cancelling returns to the previous state without showing an error', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((resolve, reject) => {
      const url = String(input);
      if (url.endsWith('/samples/index.json')) return resolve(json(sampleIndex));
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    })));
    const pending = openById('slow');
    await tick();
    expect(analysisStore.get().status).toBe('loading');
    cancelLoading();
    expect(await pending).toBe(false);
    expect(analysisStore.get()).toMatchObject({ status: 'idle', error: null, progress: null });
  });
});

describe('analysing an upload', () => {
  class Xhr {
    static last: Xhr | null = null;
    upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;
    status = 0;
    responseText = '';
    responseType = '';
    constructor() { Xhr.last = this; }
    open() {}
    setRequestHeader() {}
    send() {}
    abort() { this.onabort?.(); }
    finish(status: number, body: unknown) { this.status = status; this.responseText = JSON.stringify(body); this.onload?.(); }
  }
  const file = new File([new Uint8Array(4)], 'speech.wav', { type: 'audio/wav' });
  beforeEach(() => vi.stubGlobal('XMLHttpRequest', Xhr));

  it('moves from uploading to analysing and opens the result with the file as its audio', async () => {
    const run = analyzeFile(file, { baselineId: 'b', passageId: 'p' });
    expect(analysisStore.get().progress).toMatchObject({ phase: 'uploading' });
    Xhr.last!.upload.onprogress?.({ lengthComputable: true, loaded: 2, total: 4 });
    expect(analysisStore.get().progress).toMatchObject({ phase: 'uploading', loaded: 2, total: 4 });
    Xhr.last!.upload.onprogress?.({ lengthComputable: true, loaded: 4, total: 4 });
    expect(analysisStore.get().progress).toMatchObject({ phase: 'analysing' });
    Xhr.last!.finish(200, { ...mixedResult, analysis_id: 'uploaded-1' });
    expect(await run).toBe(true);
    expect(analysisStore.get().current).toMatchObject({ id: 'uploaded-1', source: 'upload', title: 'speech.wav', audioUrl: 'blob:test' });
  });
  it('keeps the API’s own explanation when the analysis is rejected', async () => {
    const run = analyzeFile(file, { baselineId: 'b', passageId: 'p' });
    Xhr.last!.finish(400, { error: 'UNSUPPORTED_AUDIO_FORMAT', detail: 'unsupported audio extension' });
    expect(await run).toBe(false);
    expect(analysisStore.get().status).toBe('error');
    expect(analysisStore.get().error).toBeInstanceOf(ApiError);
    expect(analysisStore.get().error).toMatchObject({ code: 'UNSUPPORTED_AUDIO_FORMAT', detail: 'unsupported audio extension' });
  });
  it('can be cancelled while uploading', async () => {
    const run = analyzeFile(file, { baselineId: 'b', passageId: 'p' });
    cancelLoading();
    expect(await run).toBe(false);
    expect(analysisStore.get()).toMatchObject({ status: 'idle', error: null, progress: null });
  });
});

describe('history list', () => {
  it('keeps one entry per analysis, newest first, and caps its length', () => {
    for (let i = 0; i < 45; i++) recordHistory({ ...mixedResult, analysis_id: `id-${i}` }, `T${i}`, 'upload');
    recordHistory({ ...mixedResult, analysis_id: 'id-10' }, 'again', 'upload');
    const list = historyStore.get();
    expect(list).toHaveLength(40);
    expect(list[0]!.id).toBe('id-10');
    expect(list.filter((e) => e.id === 'id-10')).toHaveLength(1);
  });
  it('persists to local storage', () => {
    recordHistory(mixedResult, 'Saved', 'sample', 'mixed-flaws');
    expect(JSON.parse(localStorage.getItem('sa.history.v1')!)[0]).toMatchObject({ title: 'Saved', sampleId: 'mixed-flaws' });
  });
});
