import { act, render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { vi } from 'vitest';
import { sampleIndex, hesitantResult, cleanResult, mixedResult, rushedResult } from './fixtures';

/** Layout does not exist in jsdom; give every element a fixed width so width-driven charts draw something. */
export function stubLayout(width = 900, height = 600) {
  return vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    x: 0, y: 0, left: 0, top: 0, right: width, bottom: height, width, height, toJSON: () => ({}),
  } as DOMRect);
}

/** Make `(min-width: …)` queries match, as on a wide screen. */
export function stubWideScreen(wide: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: wide && query.includes('min-width'),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

const RESULTS: Record<string, unknown> = {
  'clean-delivery.json': cleanResult,
  'hesitant-delivery.json': hesitantResult,
  'mixed-flaws.json': mixedResult,
  'rushed-explanation.json': rushedResult,
};

/** A fetch that serves the demo samples and a healthy API, and records what was requested. */
export function stubFetch(extra: Record<string, () => Response> = {}) {
  const calls: string[] = [];
  const impl = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.pathname : input.url;
    calls.push(url);
    for (const [fragment, make] of Object.entries(extra)) if (url.includes(fragment)) return make();
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
    if (url.endsWith('/samples/index.json')) return json(sampleIndex);
    const sample = Object.keys(RESULTS).find((name) => url.endsWith(`/samples/${name}`));
    if (sample) return json(RESULTS[sample]);
    if (url.endsWith('/api/v1/health')) return json({ status: 'ok', api_contract_version: '1.2.0', config_version: '1.0.0', pipeline_version: '1.0.0' });
    if (url.endsWith('/api/v1/baselines')) return json({ baselines: [], unavailable: [] });
    return json({ error: 'RESULT_NOT_FOUND', detail: 'not found' }, 404);
  });
  vi.stubGlobal('fetch', impl);
  return { impl, calls };
}

/** Render and let the effects that load data settle inside act(), so no update lands outside it. */
export async function renderAsync(ui: ReactElement) {
  let result!: ReturnType<typeof render>;
  await act(async () => {
    result = render(ui);
  });
  await act(async () => undefined);
  return result;
}
