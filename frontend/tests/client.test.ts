import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, createClient, fetchSampleIndex, fetchSampleResult, isSupportedAudioName, normalizeAudioFile } from '@/api/client';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('createClient (GET endpoints)', () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal('fetch', fetchMock));
  afterEach(() => { fetchMock.mockReset(); vi.unstubAllGlobals(); });

  it('requests the versioned path on the configured base', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }));
    const client = createClient(() => 'http://api.test');
    await client.health();
    expect(fetchMock.mock.calls[0]![0]).toBe('http://api.test/api/v1/health');
  });
  it('uses the same origin when no base is set and encodes ids', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    const client = createClient();
    await client.result('a b/c');
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/v1/result/a%20b%2Fc');
  });
  it('turns the API error body into an ApiError', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: 'RESULT_NOT_FOUND', detail: 'no such result', analysis_id: 'x' }, 404));
    const error = await createClient().result('x').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: 'RESULT_NOT_FOUND', detail: 'no such result', status: 404, analysisId: 'x' });
  });
  it('explains a non-JSON error response without leaking its body', async () => {
    fetchMock.mockResolvedValue(new Response('<html>boom</html>', { status: 502, statusText: 'Bad Gateway' }));
    const error = (await createClient().health().catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe('HTTP_ERROR');
    expect(error.detail).toContain('502');
    expect(error.detail).not.toContain('boom');
  });
  it('reports an unreachable API', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const error = (await createClient().health().catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe('NETWORK_ERROR');
  });
  it('reports a cancelled request as ABORTED', async () => {
    const controller = new AbortController();
    fetchMock.mockImplementation(() => { controller.abort(); return Promise.reject(new DOMException('aborted', 'AbortError')); });
    const error = (await createClient().health(controller.signal).catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe('ABORTED');
  });
  it('rejects a 200 that is not JSON', async () => {
    fetchMock.mockResolvedValue(new Response('plain text', { status: 200 }));
    const error = (await createClient().health().catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe('BAD_RESPONSE');
  });
});

/** A stand-in for XMLHttpRequest that lets a test decide how the upload ends. */
class FakeXhr {
  static last: FakeXhr | null = null;
  method = '';
  url = '';
  body: FormData | null = null;
  headers: Record<string, string> = {};
  status = 0;
  responseText = '';
  responseType = '';
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  constructor() { FakeXhr.last = this; }
  open(method: string, url: string) { this.method = method; this.url = url; }
  setRequestHeader(name: string, value: string) { this.headers[name] = value; }
  send(body: FormData) { this.body = body; }
  abort() { this.onabort?.(); }
  finish(status: number, body: unknown) { this.status = status; this.responseText = typeof body === 'string' ? body : JSON.stringify(body); this.onload?.(); }
}

describe('createClient.analyze (upload)', () => {
  beforeEach(() => vi.stubGlobal('XMLHttpRequest', FakeXhr));
  afterEach(() => { vi.unstubAllGlobals(); FakeXhr.last = null; });
  const audio = new File([new Uint8Array(4)], 'talk.wav', { type: '' });

  it('posts the file and the parameters as multipart form data', async () => {
    const promise = createClient(() => 'http://api.test').analyze(audio, { baselineId: 'b', passageId: 'p' });
    const xhr = FakeXhr.last!;
    expect(xhr.method).toBe('POST');
    expect(xhr.url).toBe('http://api.test/api/v1/analyze');
    expect(xhr.body!.get('baseline_id')).toBe('b');
    expect(xhr.body!.get('passage_id')).toBe('p');
    expect((xhr.body!.get('participant_audio') as File).type).toBe('audio/wav');
    expect(xhr.body!.has('manual_transcript')).toBe(false);
    xhr.finish(200, { analysis_id: 'abc' });
    await expect(promise).resolves.toMatchObject({ analysis_id: 'abc' });
  });
  it('sends a manual transcript only when it has content', async () => {
    const blank = createClient().analyze(audio, { baselineId: 'b', passageId: 'p', manualTranscript: '   ' });
    expect(FakeXhr.last!.body!.has('manual_transcript')).toBe(false);
    FakeXhr.last!.finish(200, {});
    await blank;
    const filled = createClient().analyze(audio, { baselineId: 'b', passageId: 'p', manualTranscript: '  hello there ' });
    expect(FakeXhr.last!.body!.get('manual_transcript')).toBe('hello there');
    FakeXhr.last!.finish(200, {});
    await filled;
  });
  it('reports upload progress', async () => {
    const seen: number[][] = [];
    const promise = createClient().analyze(audio, { baselineId: 'b', passageId: 'p' }, { onUploadProgress: (l, t) => seen.push([l, t]) });
    FakeXhr.last!.upload.onprogress?.({ lengthComputable: true, loaded: 2, total: 4 });
    FakeXhr.last!.upload.onprogress?.({ lengthComputable: false, loaded: 3, total: 0 });
    FakeXhr.last!.finish(200, {});
    await promise;
    expect(seen).toEqual([[2, 4]]);
  });
  it('maps an API error to an ApiError', async () => {
    const promise = createClient().analyze(audio, { baselineId: 'b', passageId: 'p' });
    FakeXhr.last!.finish(400, { error: 'AUDIO_TOO_LONG', detail: 'too long' });
    await expect(promise).rejects.toMatchObject({ code: 'AUDIO_TOO_LONG', detail: 'too long', status: 400 });
  });
  it('handles an unparseable error and a network failure', async () => {
    const odd = createClient().analyze(audio, { baselineId: 'b', passageId: 'p' });
    FakeXhr.last!.finish(500, 'oops');
    await expect(odd).rejects.toMatchObject({ code: 'HTTP_ERROR', status: 500 });
    const down = createClient().analyze(audio, { baselineId: 'b', passageId: 'p' });
    FakeXhr.last!.onerror?.();
    await expect(down).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
  });
  it('cancels through the abort signal', async () => {
    const controller = new AbortController();
    const promise = createClient().analyze(audio, { baselineId: 'b', passageId: 'p' }, { signal: controller.signal });
    controller.abort();
    await expect(promise).rejects.toMatchObject({ code: 'ABORTED' });
  });
  it('does not start when already cancelled', async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(createClient().analyze(audio, { baselineId: 'b', passageId: 'p' }, { signal: controller.signal })).rejects.toMatchObject({ code: 'ABORTED' });
  });
});

describe('file helpers', () => {
  it('sets the content type from the extension, which the API cross-checks', () => {
    expect(normalizeAudioFile(new File([''], 'a.WAV', { type: '' })).type).toBe('audio/wav');
    expect(normalizeAudioFile(new File([''], 'b.mp3', { type: 'application/octet-stream' })).type).toBe('audio/mpeg');
    const already = new File([''], 'c.wav', { type: 'audio/wav' });
    expect(normalizeAudioFile(already)).toBe(already);
    expect(normalizeAudioFile(new File([''], 'a.WAV', { type: '' })).name).toBe('a.WAV');
  });
  it('accepts WAV and MP3 names only', () => {
    expect(isSupportedAudioName('x.wav')).toBe(true);
    expect(isSupportedAudioName('x.MP3')).toBe(true);
    expect(isSupportedAudioName('x.m4a')).toBe(false);
    expect(isSupportedAudioName('wav')).toBe(false);
  });
});

describe('demo sample files', () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal('fetch', fetchMock));
  afterEach(() => { fetchMock.mockReset(); vi.unstubAllGlobals(); });
  it('loads the index and a result', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ samples: [] })).mockResolvedValueOnce(jsonResponse({ analysis_id: 'x' }));
    await expect(fetchSampleIndex()).resolves.toEqual({ samples: [] });
    await expect(fetchSampleResult('a.json')).resolves.toEqual({ analysis_id: 'x' });
    expect(fetchMock.mock.calls[0]![0]).toMatch(/samples\/index\.json$/);
  });
  it('explains when the samples are not installed', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 404 }));
    await expect(fetchSampleIndex()).rejects.toMatchObject({ code: 'HTTP_ERROR', status: 404 });
    fetchMock.mockRejectedValue(new TypeError('offline'));
    await expect(fetchSampleIndex()).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
  });
});

describe('createClient custom passages', () => {
  const fetchMock = vi.fn();
  beforeEach(() => vi.stubGlobal('XMLHttpRequest', FakeXhr));
  afterEach(() => { vi.unstubAllGlobals(); FakeXhr.last = null; fetchMock.mockReset(); });
  const take = (name: string) => new File([new Uint8Array(4)], name, { type: '' });

  it('posts the passage, the name when there is one, and every recording', async () => {
    const promise = createClient(() => 'http://api.test').createCustomBaseline({ passageText: 'Some text. More text.', title: '  My talk ', files: [take('one.wav'), take('two.mp3')] });
    const xhr = FakeXhr.last!;
    expect(xhr.method).toBe('POST');
    expect(xhr.url).toBe('http://api.test/api/v1/custom/baselines');
    expect(xhr.body!.get('passage_text')).toBe('Some text. More text.');
    expect(xhr.body!.get('title')).toBe('My talk');
    const sent = xhr.body!.getAll('baseline_audio') as File[];
    expect(sent.map((f) => [f.name, f.type])).toEqual([['one.wav', 'audio/wav'], ['two.mp3', 'audio/mpeg']]);
    xhr.finish(200, { baseline_id: 'custom-0123456789ab' });
    await expect(promise).resolves.toMatchObject({ baseline_id: 'custom-0123456789ab' });
  });
  it('leaves the name out when it is blank', async () => {
    const promise = createClient().createCustomBaseline({ passageText: 'Text.', title: '   ', files: [take('a.wav')] });
    expect(FakeXhr.last!.body!.has('title')).toBe(false);
    FakeXhr.last!.finish(200, {});
    await promise;
  });
  it('maps a refusal, a broken answer, a network failure and a cancellation', async () => {
    const refused = createClient().createCustomBaseline({ passageText: 'x', files: [take('a.wav')] });
    FakeXhr.last!.finish(422, { error: 'VALIDATION_ERROR', detail: 'The passage has 3 words.' });
    await expect(refused).rejects.toMatchObject({ code: 'VALIDATION_ERROR', detail: 'The passage has 3 words.', status: 422 });
    const odd = createClient().createCustomBaseline({ passageText: 'x', files: [take('a.wav')] });
    FakeXhr.last!.finish(500, 'oops');
    await expect(odd).rejects.toMatchObject({ code: 'HTTP_ERROR' });
    const down = createClient().createCustomBaseline({ passageText: 'x', files: [take('a.wav')] });
    FakeXhr.last!.onerror?.();
    await expect(down).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
    const controller = new AbortController();
    const cancelled = createClient().createCustomBaseline({ passageText: 'x', files: [take('a.wav')] }, { signal: controller.signal });
    controller.abort();
    await expect(cancelled).rejects.toMatchObject({ code: 'ABORTED' });
  });
  it('reports upload progress', async () => {
    const seen: number[][] = [];
    const promise = createClient().createCustomBaseline({ passageText: 'x', files: [take('a.wav')] }, { onUploadProgress: (l, t) => seen.push([l, t]) });
    FakeXhr.last!.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 4 });
    FakeXhr.last!.finish(200, {});
    await promise;
    expect(seen).toEqual([[1, 4]]);
  });
  it('deletes by id with the DELETE method and maps errors', async () => {
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockResolvedValueOnce(jsonResponse({ baseline_id: 'custom-0123456789ab', deleted: true }));
    await expect(createClient(() => 'http://api.test').deleteCustomBaseline('custom-0123456789ab')).resolves.toEqual({ baseline_id: 'custom-0123456789ab', deleted: true });
    expect(fetchMock.mock.calls[0]![0]).toBe('http://api.test/api/v1/custom/baselines/custom-0123456789ab');
    expect(fetchMock.mock.calls[0]![1]).toMatchObject({ method: 'DELETE' });
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: 'BASELINE_NOT_FOUND', detail: 'No custom baseline exists.' }, 404));
    await expect(createClient().deleteCustomBaseline('custom-0123456789ab')).rejects.toMatchObject({ code: 'BASELINE_NOT_FOUND', status: 404 });
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await expect(createClient().deleteCustomBaseline('x')).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
  });
});
