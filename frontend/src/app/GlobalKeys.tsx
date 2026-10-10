import { useEffect } from 'react';
import { analysisPath, navigate, routeStore, type AnalysisView } from './router';
import { analysisStore } from '@/state/analysis';
import { exportResultJson, stepFlaw, toggleSidebar, toggleTheme, togglePlayback } from '@/state/actions';
import { playerStore, seekBy, seek } from '@/state/player';
import { selectFlaw, setOverlay, overlayStore, selectionStore } from '@/state/ui';

const VIEW_KEYS: Record<string, AnalysisView> = {
  '1': 'overview', '2': 'timeline', '3': 'flaws', '4': 'signals', '5': 'transcript', '6': 'baseline',
};

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

function isInteractive(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return !!target.closest('button, a, [role="radio"], [role="switch"], [role="option"], [role="menuitem"], summary');
}

/**
 * Global keyboard shortcuts. Printable shortcuts never fire while typing in a field; Space and the arrow keys leave buttons and links
 * alone so keyboard users can still operate them. The list shown to users lives in features/help/shortcuts.ts.
 */
export function GlobalKeys() {
  useEffect(() => {
    let chord: number | undefined;
    let pendingG = false;

    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOverlay({ palette: !overlayStore.get().palette });
        return;
      }
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
      const overlays = overlayStore.get();
      if (overlays.palette || overlays.shortcuts) return;
      if (isTypingTarget(e.target)) return;

      const route = routeStore.get();
      const current = analysisStore.get().current;
      const onAnalysis = route.name === 'analysis' && current !== null;

      if (pendingG) {
        pendingG = false;
        window.clearTimeout(chord);
        const target = { n: '/', l: '/library', s: '/settings', h: '/help' }[e.key.toLowerCase()];
        if (target) {
          e.preventDefault();
          navigate(target);
          return;
        }
      }

      switch (e.key) {
        case '?':
          e.preventDefault();
          setOverlay({ shortcuts: true });
          return;
        case 'g':
          pendingG = true;
          window.clearTimeout(chord);
          chord = window.setTimeout(() => (pendingG = false), 1200);
          return;
        case 'b':
        case 'B':
          e.preventDefault();
          toggleSidebar();
          return;
        case 't':
        case 'T':
          e.preventDefault();
          toggleTheme();
          return;
        case 'Escape':
          if (overlays.mobileNav) setOverlay({ mobileNav: false });
          else if (selectionStore.get().flawId) selectFlaw(null);
          return;
        default:
      }

      if (!current) return;
      const view = VIEW_KEYS[e.key];
      if (view) {
        e.preventDefault();
        navigate(analysisPath(current.id, view));
        return;
      }
      if (!onAnalysis) return;

      switch (e.key) {
        case ' ':
          if (isInteractive(e.target)) return;
          e.preventDefault();
          togglePlayback();
          return;
        case 'ArrowLeft':
        case 'ArrowRight':
          if (isInteractive(e.target) || !playerStore.get().src) return;
          e.preventDefault();
          seekBy((e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 5 : 1));
          return;
        case 'Home':
          if (!playerStore.get().src) return;
          e.preventDefault();
          seek(0);
          return;
        case '[':
          e.preventDefault();
          stepFlaw(-1);
          return;
        case ']':
          e.preventDefault();
          stepFlaw(1);
          return;
        case 'e':
        case 'E':
          e.preventDefault();
          exportResultJson();
          return;
        default:
      }
    };

    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.clearTimeout(chord);
    };
  }, []);
  return null;
}
