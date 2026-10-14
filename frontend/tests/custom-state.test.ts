import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import { catalogStore } from '@/state/connection';
import { cancelCustom, createCustomBaseline, customStore, deleteCustomBaseline, resetCustom } from '@/state/custom';
import { api } from '@/state/api';

const made = { baseline_id: 'custom-0123456789ab', passage_id: 'custom-0123456789ab', title: 'T', passage_text: 'x', passage_word_count: 1, n_recordings: 2,
  already_existed: false, word_profile_built: false, pitch_profile_built: false, takes: [], warnings: [] };
const params = { passageText: 'One. Two.', files: [new File([new Uint8Array(2)], 'a.wav')] };

beforeEach(() => { resetCustom(); catalogStore.set({ status: 'idle', data: null, error: null }); });
afterEach(() => vi.restoreAllMocks());

describe('making a custom baseline', () => {
  it('goes through uploading and building, keeps the result and refreshes the catalogue', async () => {
    const baselines = vi.spyOn(api, 'baselines').mockResolvedValue({ baselines: [], unavailable: [] });
    const seen: string[] = [];
    vi.spyOn(api, 'createCustomBaseline').mockImplementation(async (_p, options) => {
      options?.onUploadProgress?.(1, 4);
      seen.push(customStore.get().progress!.phase);
      options?.onUploadProgress?.(4, 4);
      seen.push(customStore.get().progress!.phase);
      return made as never;
    });
    const promise = createCustomBaseline(params);
    expect(customStore.get().status).toBe('working');
    expect(await promise).toBe(true);
    expect(seen).toEqual(['uploading', 'building']);
    expect(customStore.get()).toMatchObject({ status: 'ready', progress: null, error: null, result: { baseline_id: 'custom-0123456789ab' } });
    expect(baselines).toHaveBeenCalled();
  });
  it('keeps the server\'s reason when it refuses', async () => {
    vi.spyOn(api, 'createCustomBaseline').mockRejectedValue(new ApiError('VALIDATION_ERROR', 'The passage has 3 words.', 422));
    expect(await createCustomBaseline(params)).toBe(false);
    expect(customStore.get()).toMatchObject({ status: 'error', result: null, error: { code: 'VALIDATION_ERROR', detail: 'The passage has 3 words.' } });
  });
  it('turns an unexpected failure into a network error the page can show', async () => {
    vi.spyOn(api, 'createCustomBaseline').mockRejectedValue(new Error('boom'));
    await createCustomBaseline(params);
    expect(customStore.get().error).toMatchObject({ code: 'NETWORK_ERROR', detail: 'boom' });
  });
  it('goes back to idle when cancelled, and a newer request replaces an older one', async () => {
    vi.spyOn(api, 'createCustomBaseline').mockImplementation((_p, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener('abort', () => reject(new ApiError('ABORTED', 'cancelled')));
    }));
    const first = createCustomBaseline(params);
    cancelCustom();
    expect(await first).toBe(false);
    expect(customStore.get().status).toBe('idle');
    const older = createCustomBaseline(params);
    vi.spyOn(api, 'createCustomBaseline').mockResolvedValue(made as never);
    expect(await createCustomBaseline(params)).toBe(true);
    expect(await older).toBe(false);
    expect(customStore.get().status).toBe('ready');
  });
});

describe('deleting a custom baseline', () => {
  it('forgets a result that was just deleted and refreshes the catalogue', async () => {
    vi.spyOn(api, 'baselines').mockResolvedValue({ baselines: [], unavailable: [] });
    customStore.set({ status: 'ready', progress: null, result: made as never, error: null });
    vi.spyOn(api, 'deleteCustomBaseline').mockResolvedValue({ baseline_id: made.baseline_id, deleted: true });
    expect(await deleteCustomBaseline(made.baseline_id)).toBe(true);
    expect(customStore.get().status).toBe('idle');
  });
  it('treats "already gone" as done, and keeps the error of any other failure', async () => {
    vi.spyOn(api, 'baselines').mockResolvedValue({ baselines: [], unavailable: [] });
    vi.spyOn(api, 'deleteCustomBaseline').mockRejectedValueOnce(new ApiError('BASELINE_NOT_FOUND', 'gone', 404));
    expect(await deleteCustomBaseline('custom-0123456789ab')).toBe(true);
    vi.spyOn(api, 'deleteCustomBaseline').mockRejectedValueOnce(new ApiError('NETWORK_ERROR', 'down'));
    expect(await deleteCustomBaseline('custom-0123456789ab')).toBe(false);
    expect(customStore.get().error).toMatchObject({ code: 'NETWORK_ERROR' });
  });
});
