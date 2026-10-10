import { Icon } from '@/components/Icon';
import { IconButton, Kbd } from '@/components/ui';
import { resolveTheme, useSettings } from '@/lib/settings';
import { useCurrent } from '@/state/analysis';
import { copyPageLink, exportResultJson, toggleTheme } from '@/state/actions';
import { setOverlay } from '@/state/ui';
import { analysisPath, navigate, useRoute, VIEW_LABEL } from './router';

export function Topbar() {
  const route = useRoute();
  const current = useCurrent();
  const settings = useSettings();
  const systemDark = typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const dark = resolveTheme(settings.theme, systemDark) === 'dark';

  let eyebrow = 'Workspace';
  let title = 'New analysis';
  if (route.name === 'library') title = 'Library';
  else if (route.name === 'settings') { eyebrow = 'System'; title = 'Settings'; }
  else if (route.name === 'help') { eyebrow = 'System'; title = 'Help & shortcuts'; }
  else if (route.name === 'notfound') { eyebrow = 'Error'; title = 'Page not found'; }
  else if (route.name === 'analysis') {
    eyebrow = current && current.id === route.id ? current.title : 'Analysis';
    title = VIEW_LABEL[route.view];
  }
  const modifier = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl';

  return (
    <header className="topbar no-print">
      <button type="button" className="topbar__menu icon-btn" aria-label="Open navigation" onClick={() => setOverlay({ mobileNav: true })}>
        <Icon name="menu" size={20} />
      </button>
      <div className="topbar__title">
        <span className="eyebrow truncate">{eyebrow}</span>
        <h1 className="topbar__h1 truncate">{title}</h1>
      </div>
      <div className="topbar__spacer" />
      <button type="button" className="palette-trigger" onClick={() => setOverlay({ palette: true })} aria-label="Search and jump to anything">
        <Icon name="search" size={15} />
        <span className="palette-trigger__text">Search or jump to…</span>
        <span className="palette-trigger__keys"><Kbd>{modifier}</Kbd><Kbd>K</Kbd></span>
      </button>
      {current && route.name === 'analysis' ? (
        <>
          <IconButton icon="link" label="Copy a link to this page" onClick={() => void copyPageLink()} />
          <IconButton icon="download" label="Export result as JSON (E)" onClick={exportResultJson} />
          <IconButton icon="printer" label="Open the printable report" onClick={() => navigate(analysisPath(current.id, 'report'))} active={route.view === 'report'} />
        </>
      ) : null}
      <IconButton icon={dark ? 'sun' : 'moon'} label={`Switch to ${dark ? 'light' : 'dark'} mode (T)`} onClick={toggleTheme} />
    </header>
  );
}
