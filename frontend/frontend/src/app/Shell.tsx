import { useEffect, type ReactNode } from 'react';
import { Dialog, Toasts } from '@/components/ui';
import { ShortcutList } from '@/features/help/ShortcutList';
import { useSettings } from '@/lib/settings';
import { useCurrent } from '@/state/analysis';
import { usePlayer } from '@/state/player';
import { setOverlay, useOverlays } from '@/state/ui';
import { CommandPalette } from './CommandPalette';
import { GlobalKeys } from './GlobalKeys';
import { Ribbon } from './Ribbon';
import { useRoute } from './router';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';
import { Transport } from './Transport';

/** The application frame: sidebar, top bar, the whole-recording ribbon, the page, and the playback bar. */
export function Shell({ children, fill }: { children: ReactNode; fill?: boolean }) {
  const settings = useSettings();
  const route = useRoute();
  const current = useCurrent();
  const player = usePlayer();
  const overlays = useOverlays();
  // The ribbon and the playback bar belong to the analysis that is actually open, not to whatever the address bar names.
  const onAnalysis = route.name === 'analysis' && current !== null && current.id === route.id && route.view !== 'report';

  // The small-screen navigation drawer closes whenever the page changes, however the change was made (a link, Back, the palette, a key).
  const routeKey = route.name === 'analysis' ? `${route.id}/${route.view}/${route.flawId ?? ''}` : route.name;
  useEffect(() => { setOverlay({ mobileNav: false }); }, [routeKey]);

  return (
    <div className="app" data-collapsed={settings.sidebarCollapsed}>
      <a className="skip-link" href="#main">Skip to content</a>
      <Sidebar />
      {overlays.mobileNav ? <div className="nav-scrim" onClick={() => setOverlay({ mobileNav: false })} aria-hidden="true" /> : null}
      <div className="main">
        <Topbar />
        {onAnalysis ? <Ribbon /> : null}
        <main id="main" className={`content ${fill ? 'content--fill' : ''}`} tabIndex={0}>
          {children}
        </main>
        {onAnalysis && player.src ? <Transport /> : null}
      </div>
      <Toasts />
      <CommandPalette />
      <Dialog open={overlays.shortcuts} onClose={() => setOverlay({ shortcuts: false })} title="Keyboard shortcuts" wide>
        <ShortcutList />
      </Dialog>
      <GlobalKeys />
    </div>
  );
}
