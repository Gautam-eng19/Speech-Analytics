import { createStore, useStore } from '@/lib/store';

/**
 * Hash routing (#/a/<analysis id>/timeline). No server support is needed, links to a result can be shared, and the same build works
 * when it is served by the API, by Vite, or from a static folder.
 */
export type AnalysisView = 'overview' | 'timeline' | 'flaws' | 'signals' | 'transcript' | 'baseline' | 'report';

export type Route =
  | { name: 'analyze' }
  | { name: 'library' }
  | { name: 'custom' }
  | { name: 'settings' }
  | { name: 'help' }
  | { name: 'analysis'; id: string; view: AnalysisView; flawId: string | null }
  | { name: 'notfound'; path: string };

export const VIEW_LABEL: Record<AnalysisView, string> = {
  overview: 'Overview', timeline: 'Timeline', flaws: 'Flaws', signals: 'Signals', transcript: 'Transcript', baseline: 'Baseline & method', report: 'Report',
};

const VIEWS: readonly AnalysisView[] = ['overview', 'timeline', 'flaws', 'signals', 'transcript', 'baseline', 'report'];

export function parseRoute(hash: string): Route {
  const path = hash.replace(/^#/, '').split('?')[0] ?? '';
  const parts = path.split('/').filter(Boolean);
  if (parts.length === 0) return { name: 'analyze' };
  const [head, second, third, fourth] = parts;
  if (head === 'library' && parts.length === 1) return { name: 'library' };
  if (head === 'custom' && parts.length === 1) return { name: 'custom' };
  if (head === 'settings' && parts.length === 1) return { name: 'settings' };
  if (head === 'help' && parts.length === 1) return { name: 'help' };
  if (head === 'a' && second) {
    try {
      const id = decodeURIComponent(second);
      const view = (third ?? 'overview') as AnalysisView;
      if (!VIEWS.includes(view)) return { name: 'notfound', path };
      if (parts.length === 4 && view === 'flaws' && fourth) return { name: 'analysis', id, view, flawId: decodeURIComponent(fourth) };
      if (parts.length <= 3) return { name: 'analysis', id, view, flawId: null };
    } catch {
      /* malformed percent-encoding: fall through to not found */
    }
  }
  return { name: 'notfound', path };
}

export const analysisPath = (id: string, view: AnalysisView = 'overview', flawId?: string | null): string =>
  `/a/${encodeURIComponent(id)}/${view}${flawId ? `/${encodeURIComponent(flawId)}` : ''}`;

export const routeStore = createStore<Route>(parseRoute(typeof window === 'undefined' ? '' : window.location.hash));

export function bindRouter(): () => void {
  const onChange = () => routeStore.set(parseRoute(window.location.hash));
  window.addEventListener('hashchange', onChange);
  onChange();
  return () => window.removeEventListener('hashchange', onChange);
}

export function navigate(path: string, options: { replace?: boolean } = {}): void {
  const hash = `#${path.startsWith('/') ? path : `/${path}`}`;
  if (window.location.hash === hash) return;
  if (options.replace) window.location.replace(hash);
  else window.location.hash = hash;
}

export const useRoute = (): Route => useStore(routeStore, (r) => r);
