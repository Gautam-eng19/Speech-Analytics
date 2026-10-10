import { Icon, LogoMark, type IconName } from '@/components/Icon';
import { Chip, IconButton, Tip } from '@/components/ui';
import { resolveTheme, updateSettings, useSettings } from '@/lib/settings';
import { fmtNum } from '@/lib/format';
import { closeAnalysis, useCurrent } from '@/state/analysis';
import { useConnection } from '@/state/connection';
import { toggleSidebar } from '@/state/actions';
import { setOverlay, useOverlays } from '@/state/ui';
import { analysisPath, navigate, useRoute, type AnalysisView } from './router';

interface NavDef {
  view: AnalysisView;
  label: string;
  icon: IconName;
  key: string;
}

const ANALYSIS_NAV: NavDef[] = [
  { view: 'overview', label: 'Overview', icon: 'gauge', key: '1' },
  { view: 'timeline', label: 'Timeline', icon: 'gantt', key: '2' },
  { view: 'flaws', label: 'Flaws', icon: 'flag', key: '3' },
  { view: 'signals', label: 'Signals', icon: 'chart', key: '4' },
  { view: 'transcript', label: 'Transcript', icon: 'text', key: '5' },
  { view: 'baseline', label: 'Baseline & method', icon: 'ruler', key: '6' },
];

function NavItem({ href, icon, label, active, collapsed, badge, hint, disabled }: {
  href?: string; icon: IconName; label: string; active?: boolean; collapsed: boolean; badge?: string | number; hint?: string; disabled?: boolean;
}) {
  const body = (
    <>
      <Icon name={icon} size={18} />
      {collapsed ? null : <span className="nav-item__label">{label}</span>}
      {!collapsed && badge !== undefined ? <span className="nav-item__badge num">{badge}</span> : null}
      {!collapsed && hint && badge === undefined ? <span className="nav-item__hint">{hint}</span> : null}
    </>
  );
  const cls = `nav-item ${active ? 'is-active' : ''} ${disabled ? 'is-disabled' : ''}`;
  const node = disabled || !href ? (
    <span className={cls} aria-disabled="true" aria-label={collapsed ? label : undefined}>{body}</span>
  ) : (
    <a className={cls} href={`#${href}`} aria-label={collapsed ? label : undefined} aria-current={active ? 'page' : undefined} onClick={(e) => { e.preventDefault(); navigate(href); setOverlay({ mobileNav: false }); }}>
      {body}
    </a>
  );
  return collapsed ? <Tip text={label} side="right">{node}</Tip> : node;
}

function ConnectionStatus({ collapsed }: { collapsed: boolean }) {
  const connection = useConnection();
  const label = connection.status === 'online' ? 'API online' : connection.status === 'offline' ? 'API offline' : 'Checking API';
  const detail = connection.health
    ? `API ${connection.health.api_contract_version} · config ${connection.health.config_version} · pipeline ${connection.health.pipeline_version}`
    : connection.status === 'offline' ? 'The backend is not reachable. Demo samples still work.' : 'Contacting the backend…';
  const body = (
    <div className={`conn conn--${connection.status}`}>
      <span className="conn__led" aria-hidden="true" />
      {collapsed ? <span className="sr-only">{label}</span> : <span className="conn__text">{label}</span>}
    </div>
  );
  return <Tip text={detail} side={collapsed ? 'right' : 'top'}>{body}</Tip>;
}

function ThemeSwitch({ collapsed }: { collapsed: boolean }) {
  const settings = useSettings();
  const systemDark = typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const showing = resolveTheme(settings.theme, systemDark);
  if (collapsed) {
    return <IconButton icon={showing === 'dark' ? 'moon' : 'sun'} label={`Theme: ${settings.theme}. Click for ${showing === 'dark' ? 'light' : 'dark'}.`} onClick={() => updateSettings({ theme: showing === 'dark' ? 'light' : 'dark' })} />;
  }
  return (
    <div className="seg seg--sm theme-seg" role="radiogroup" aria-label="Theme">
      {([['light', 'sun', 'Light'], ['system', 'monitor', 'System'], ['dark', 'moon', 'Dark']] as const).map(([value, icon, label]) => (
        <button key={value} type="button" role="radio" aria-checked={settings.theme === value} aria-label={label} title={label} className={settings.theme === value ? 'is-on' : ''} onClick={() => updateSettings({ theme: value })}>
          <Icon name={icon} size={14} />
        </button>
      ))}
    </div>
  );
}

export function Sidebar() {
  const settings = useSettings();
  const route = useRoute();
  const current = useCurrent();
  const overlays = useOverlays();
  const collapsed = settings.sidebarCollapsed && !overlays.mobileNav;
  const activeView = route.name === 'analysis' ? route.view : null;

  return (
    <aside className="sidebar" data-collapsed={collapsed} data-open={overlays.mobileNav} aria-label="Primary">
      <div className="sidebar__top">
        <a className="brand" href="#/" onClick={(e) => { e.preventDefault(); navigate('/'); setOverlay({ mobileNav: false }); }} aria-label="Speech Analytics, home">
          <LogoMark size={30} />
          {collapsed ? null : (
            <span className="brand__text">
              <span className="brand__name">Speech Analytics</span>
              <span className="brand__sub">Contrastive delivery analysis</span>
            </span>
          )}
        </a>
        {collapsed ? null : <IconButton icon="panel-left" label="Collapse sidebar (B)" onClick={toggleSidebar} className="sidebar__collapse" />}
      </div>

      <div className="sidebar__scroll">
        {current ? (
          <div className="open-card" data-collapsed={collapsed}>
            {collapsed ? (
              <Tip text={`${current.title} · ${fmtNum(current.result.scores.composite_score, 1)}`} side="right">
                <button type="button" className="open-card__mini" aria-label={`Open analysis: ${current.title}`} onClick={() => navigate(analysisPath(current.id, 'overview'))}>
                  <span className="num">{fmtNum(current.result.scores.composite_score, 0)}</span>
                </button>
              </Tip>
            ) : (
              <>
                <div className="open-card__head">
                  <span className="eyebrow">Open analysis</span>
                  <button type="button" className="open-card__close" aria-label="Close analysis" title="Close analysis" onClick={() => { closeAnalysis(); navigate('/'); }}>
                    <Icon name="x" size={14} />
                  </button>
                </div>
                <div className="open-card__title truncate" title={current.title}>{current.title}</div>
                <div className="open-card__meta">
                  <span className="num">{fmtNum(current.result.scores.composite_score, 1)}</span>
                  <span aria-hidden="true">·</span>
                  <span>{current.result.flaws.length} {current.result.flaws.length === 1 ? 'flaw' : 'flaws'}</span>
                  {current.source === 'sample' ? <Chip tone="info" icon="flask">Synthetic</Chip> : null}
                </div>
              </>
            )}
          </div>
        ) : null}

        <nav aria-label="Analysis views" className="nav-group">
          {collapsed ? <div className="nav-group__rule" /> : <div className="nav-group__label eyebrow">Analysis</div>}
          {ANALYSIS_NAV.map((item) => (
            <NavItem
              key={item.view}
              href={current ? analysisPath(current.id, item.view) : undefined}
              icon={item.icon}
              label={item.label}
              active={activeView === item.view}
              collapsed={collapsed}
              badge={item.view === 'flaws' && current ? current.result.flaws.length : undefined}
              hint={current ? item.key : undefined}
              disabled={!current}
            />
          ))}
          {!current && !collapsed ? <p className="nav-group__note">Open an analysis to enable these views.</p> : null}
        </nav>

        <nav aria-label="Workspace" className="nav-group">
          {collapsed ? <div className="nav-group__rule" /> : <div className="nav-group__label eyebrow">Workspace</div>}
          <NavItem href="/" icon="plus" label="New analysis" active={route.name === 'analyze'} collapsed={collapsed} hint="g n" />
          <NavItem href="/library" icon="layers" label="Library" active={route.name === 'library'} collapsed={collapsed} hint="g l" />
        </nav>
      </div>

      <div className="sidebar__foot">
        <nav aria-label="System" className="nav-group nav-group--tight">
          <NavItem href="/settings" icon="sliders" label="Settings" active={route.name === 'settings'} collapsed={collapsed} hint="g s" />
          <NavItem href="/help" icon="help" label="Help & shortcuts" active={route.name === 'help'} collapsed={collapsed} hint="g h" />
        </nav>
        <div className="sidebar__foot-row">
          <ConnectionStatus collapsed={collapsed} />
          <ThemeSwitch collapsed={collapsed} />
        </div>
        {collapsed ? <IconButton icon="panel-left" label="Expand sidebar (B)" onClick={toggleSidebar} className="sidebar__expand" /> : null}
      </div>
    </aside>
  );
}
