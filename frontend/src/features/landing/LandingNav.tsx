import type { MouseEvent } from 'react';
import { analysisPath, navigate } from '@/app/router';
import { Icon, LogoMark } from '@/components/Icon';
import { Button, IconButton } from '@/components/ui';
import { resolveTheme, useSettings } from '@/lib/settings';
import { useCurrent } from '@/state/analysis';
import { toggleTheme } from '@/state/actions';
import { setOverlay } from '@/state/ui';

/** The sections of the landing page the navigation jumps to, in reading order. */
export const LANDING_SECTIONS = [
  { id: 'method', label: 'Method' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'journey', label: 'Journey' },
] as const;

/** The address bar belongs to the router (#/…), so in-page jumps scroll the page and move focus instead of changing the hash. */
export function goToSection(id: string): void {
  const section = document.getElementById(id);
  if (!section) return;
  section.scrollIntoView({ block: 'start' });
  const heading = section.querySelector<HTMLElement>('[data-section-heading]');
  if (heading) heading.focus({ preventScroll: true });
}

/**
 * "New analysis" asked for from inside the app: the home page, scrolled to the analysis flow. The hero is for arriving; someone who is
 * already here, and asks for a new analysis, wants the flow (and keyboard focus lands on its heading).
 */
export function openNewAnalysis(): void {
  navigate('/');
  // The page for the new route is drawn a moment after the address changes; look for the flow until it is there (at most about 1.5 s).
  let tries = 0;
  const attempt = () => {
    if (document.getElementById('start')) goToSection('start');
    else if (++tries < 30) window.setTimeout(attempt, 50);
  };
  window.setTimeout(attempt, 30);
}

export function scrollToTop(): void {
  document.getElementById('main')?.scrollTo({ top: 0 });
}

function jump(id: string) {
  return (e: MouseEvent) => { e.preventDefault(); goToSection(id); };
}

function route(path: string) {
  return (e: MouseEvent) => { e.preventDefault(); navigate(path); };
}

export function LandingNav() {
  const settings = useSettings();
  const current = useCurrent();
  const systemDark = typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const dark = resolveTheme(settings.theme, systemDark) === 'dark';

  return (
    <header className="lnav no-print">
      <div className="lnav__inner">
        <a className="brand" href="#/" onClick={(e) => { e.preventDefault(); scrollToTop(); }} aria-label="VAANI, back to the top">
          <LogoMark size={32} />
          <span className="brand__text"><span className="brand__name">VAANI</span></span>
        </a>

        <nav className="lnav__group lnav__group--sections" aria-label="On this page">
          {LANDING_SECTIONS.map((s) => <a key={s.id} className="lnav__link" href="#/" onClick={jump(s.id)}>{s.label}</a>)}
        </nav>

        <nav className="lnav__group lnav__group--routes" aria-label="Site">
          <a className="lnav__link" href="#/library" onClick={route('/library')}>Library</a>
          <a className="lnav__link" href="#/custom" onClick={route('/custom')}>Custom passage</a>
          <a className="lnav__link" href="#/help" onClick={route('/help')}>Help</a>
        </nav>

        <div className="lnav__tools">
          {current ? (
            <a className="lnav__continue" href={`#${analysisPath(current.id, 'overview')}`} onClick={route(analysisPath(current.id, 'overview'))} title={`Continue with ${current.title}`}>
              <Icon name="gauge" size={14} /><span className="truncate">Continue · {current.title}</span>
            </a>
          ) : null}
          <IconButton icon={dark ? 'sun' : 'moon'} label={`Switch to ${dark ? 'light' : 'dark'} mode (T)`} onClick={toggleTheme} className="lnav__theme" />
          <IconButton icon="menu" label="Open navigation" onClick={() => setOverlay({ mobileNav: true })} />
          <Button variant="primary" size="sm" onClick={() => goToSection('start')} className="lnav__cta">Analyse a recording</Button>
        </div>
      </div>
    </header>
  );
}
