import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { SampleIndex } from '@/api/types';
import { Icon, type IconName } from '@/components/Icon';
import { Kbd } from '@/components/ui';
import { flawMeta } from '@/lib/flawMeta';
import { fmtNum } from '@/lib/format';
import { flawsByTime } from '@/lib/result';
import { updateSettings } from '@/lib/settings';
import { closeAnalysis, loadSamples, useCurrent } from '@/state/analysis';
import { copyPageLink, exportFindingsCsv, exportResultJson, goToFlaw, setTheme, stepFlaw, toggleSidebar, togglePlayback, toggleTheme } from '@/state/actions';
import { useHistory } from '@/state/history';
import { setOverlay, useOverlays } from '@/state/ui';
import { analysisPath, navigate, type AnalysisView } from './router';

interface Command {
  id: string;
  label: string;
  group: string;
  icon: IconName;
  hint?: string;
  keywords?: string;
  run: () => void;
}

const VIEWS: { view: AnalysisView; label: string; icon: IconName }[] = [
  { view: 'overview', label: 'Overview', icon: 'gauge' },
  { view: 'timeline', label: 'Timeline', icon: 'gantt' },
  { view: 'flaws', label: 'Flaws', icon: 'flag' },
  { view: 'signals', label: 'Signals', icon: 'chart' },
  { view: 'transcript', label: 'Transcript', icon: 'text' },
  { view: 'baseline', label: 'Baseline & method', icon: 'ruler' },
  { view: 'report', label: 'Printable report', icon: 'printer' },
];

/** Every token must appear in the haystack; earlier and tighter matches rank first. */
export function matchScore(query: string, haystack: string): number | null {
  const tokens = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return 0;
  const text = haystack.toLowerCase();
  let score = 0;
  for (const token of tokens) {
    const at = text.indexOf(token);
    if (at < 0) return null;
    score += at + (at > 0 && /\w/.test(text[at - 1] ?? '') ? 12 : 0);
  }
  return score;
}

export function CommandPalette() {
  const { palette } = useOverlays();
  const close = () => setOverlay({ palette: false });
  if (!palette) return null;
  return createPortal(<PaletteBody onClose={close} />, document.body);
}

function PaletteBody({ onClose }: { onClose: () => void }) {
  const current = useCurrent();
  const history = useHistory();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [samples, setSamples] = useState<SampleIndex | null>(null);
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    let cancelled = false;
    loadSamples().then((s) => !cancelled && setSamples(s)).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const commands = useMemo<Command[]>(() => {
    const go = (path: string) => () => navigate(path);
    const list: Command[] = [
      { id: 'go-new', group: 'Go to', label: 'New analysis', icon: 'plus', hint: 'g n', run: go('/') },
      { id: 'go-library', group: 'Go to', label: 'Library', icon: 'layers', hint: 'g l', run: go('/library') },
      { id: 'go-settings', group: 'Go to', label: 'Settings', icon: 'sliders', hint: 'g s', run: go('/settings') },
      { id: 'go-help', group: 'Go to', label: 'Help and shortcuts', icon: 'help', hint: 'g h', run: go('/help') },
    ];
    if (current) {
      VIEWS.forEach((v, i) => list.push({
        id: `view-${v.view}`, group: 'This analysis', label: v.label, icon: v.icon, hint: i < 6 ? String(i + 1) : undefined,
        keywords: `open ${current.title}`, run: go(analysisPath(current.id, v.view)),
      }));
      flawsByTime(current.result.flaws).forEach((f) => list.push({
        id: `flaw-${f.flaw_id}`, group: 'Flaws', label: `${flawMeta(f.type).label}, ${fmtNum(f.start_s, 1)}–${fmtNum(f.end_s, 1)} s`,
        icon: flawMeta(f.type).icon, keywords: `${f.flaw_id} flaw finding ${f.explanation}`,
        run: () => { goToFlaw(f); navigate(analysisPath(current.id, 'timeline')); },
      }));
      list.push(
        { id: 'act-play', group: 'Actions', label: 'Play or pause', icon: 'play', hint: 'Space', run: togglePlayback },
        { id: 'act-next', group: 'Actions', label: 'Next flaw', icon: 'skip-forward', hint: ']', run: () => stepFlaw(1) },
        { id: 'act-prev', group: 'Actions', label: 'Previous flaw', icon: 'skip-back', hint: '[', run: () => stepFlaw(-1) },
        { id: 'act-export', group: 'Actions', label: 'Export result as JSON', icon: 'download', hint: 'E', run: exportResultJson },
        { id: 'act-csv', group: 'Actions', label: 'Export findings as CSV', icon: 'download', keywords: 'spreadsheet excel table', run: exportFindingsCsv },
        { id: 'act-close', group: 'Actions', label: 'Close this analysis', icon: 'x', run: () => { closeAnalysis(); navigate('/'); } },
      );
    }
    list.push(
      { id: 'act-link', group: 'Actions', label: 'Copy a link to this page', icon: 'link', keywords: 'share url address', run: () => void copyPageLink() },
      { id: 'act-theme', group: 'Appearance', label: 'Toggle light and dark', icon: 'moon', hint: 'T', run: toggleTheme },
      { id: 'theme-light', group: 'Appearance', label: 'Theme: light', icon: 'sun', run: () => setTheme('light') },
      { id: 'theme-dark', group: 'Appearance', label: 'Theme: dark', icon: 'moon', run: () => setTheme('dark') },
      { id: 'theme-system', group: 'Appearance', label: 'Theme: follow the system', icon: 'monitor', run: () => setTheme('system') },
      { id: 'density-compact', group: 'Appearance', label: 'Density: compact', icon: 'sliders', run: () => updateSettings({ density: 'compact' }) },
      { id: 'density-comfortable', group: 'Appearance', label: 'Density: comfortable', icon: 'sliders', run: () => updateSettings({ density: 'comfortable' }) },
      { id: 'act-sidebar', group: 'Appearance', label: 'Collapse or expand the sidebar', icon: 'panel-left', hint: 'B', run: toggleSidebar },
      { id: 'act-keys', group: 'Appearance', label: 'Show keyboard shortcuts', icon: 'keyboard', hint: '?', run: () => setOverlay({ shortcuts: true }) },
    );
    samples?.samples.forEach((s) => list.push({
      id: `sample-${s.id}`, group: 'Demo samples', label: s.title, icon: 'flask', keywords: `sample synthetic demo ${s.description}`,
      run: () => navigate(analysisPath(s.analysis_id, 'overview')),
    }));
    history.slice(0, 8).forEach((h) => list.push({
      id: `hist-${h.id}`, group: 'Recent', label: h.title, icon: 'clock', hint: fmtNum(h.composite, 1), keywords: `recent ${h.baselineId}`,
      run: () => navigate(analysisPath(h.id, 'overview')),
    }));
    return list;
  }, [current, history, samples]);

  const results = useMemo(() => {
    if (!query.trim()) return commands;
    return commands
      .map((c) => ({ c, s: matchScore(query, `${c.label} ${c.group} ${c.keywords ?? ''}`) }))
      .filter((x): x is { c: Command; s: number } => x.s !== null)
      .sort((a, b) => a.s - b.s)
      .map((x) => x.c);
  }, [commands, query]);

  useEffect(() => setActive(0), [query]);
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [active, results]);

  const run = (command: Command | undefined) => {
    if (!command) return;
    onClose();
    window.setTimeout(command.run, 0);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => (results.length ? (i + 1) % results.length : 0)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => (results.length ? (i - 1 + results.length) % results.length : 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); run(results[active]); }
    else if (e.key === 'Escape') { e.preventDefault(); onClose(); }
  };

  let lastGroup = '';
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Search and jump to anything" onKeyDown={onKeyDown}>
        <div className="palette__input">
          <Icon name="search" size={18} />
          <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search pages, flaws, samples, actions…" aria-label="Search" role="combobox" aria-expanded="true" aria-controls="palette-list" aria-activedescendant={results[active] ? `cmd-${results[active]!.id}` : undefined} spellCheck={false} />
          <Kbd>Esc</Kbd>
        </div>
        <ul className="palette__list" id="palette-list" role="listbox" ref={listRef}>
          {results.length === 0 ? <li className="palette__empty">Nothing matches “{query}”.</li> : null}
          {results.map((c, i) => {
            const header = c.group !== lastGroup ? c.group : null;
            lastGroup = c.group;
            return (
              <li key={c.id} role="presentation">
                {header ? <div className="palette__group eyebrow">{header}</div> : null}
                <div id={`cmd-${c.id}`} role="option" aria-selected={i === active} className={`palette__item ${i === active ? 'is-active' : ''}`} onMouseMove={() => setActive(i)} onClick={() => run(c)}>
                  <Icon name={c.icon} size={17} />
                  <span className="palette__label truncate">{c.label}</span>
                  {c.hint ? <span className="palette__hint"><Kbd>{c.hint}</Kbd></span> : null}
                </div>
              </li>
            );
          })}
        </ul>
        <div className="palette__foot"><span><Kbd>↑</Kbd><Kbd>↓</Kbd> navigate</span><span><Kbd>Enter</Kbd> open</span></div>
      </div>
    </div>
  );
}
