import type { CSSProperties, ReactNode } from 'react';

/**
 * Custom icon set. Every icon is drawn on a 24-unit grid with one stroke weight and round joins, so the set reads as one family.
 * Flaw glyphs (`g-*`) are paired with colour wherever a flaw type is shown, so colour is never the only signal.
 */
export type IconName =
  | 'plus' | 'layers' | 'gauge' | 'gantt' | 'flag' | 'chart' | 'text' | 'ruler' | 'sliders' | 'help'
  | 'sun' | 'moon' | 'monitor' | 'chevron-left' | 'chevron-right' | 'chevron-up' | 'chevron-down'
  | 'play' | 'pause' | 'skip-back' | 'skip-forward' | 'loop' | 'search' | 'command' | 'check' | 'x'
  | 'info' | 'alert-triangle' | 'alert-circle' | 'download' | 'upload' | 'copy' | 'external' | 'trash'
  | 'panel-left' | 'clock' | 'filter' | 'sort' | 'eye' | 'eye-off' | 'zoom-in' | 'zoom-out' | 'fit'
  | 'g-fast' | 'g-slow' | 'g-pause' | 'g-quiet' | 'g-loud' | 'g-flat' | 'g-unstable' | 'g-clarity'
  | 'mic' | 'file-audio' | 'refresh' | 'bar-chart' | 'hash' | 'shield-check' | 'book' | 'keyboard' | 'printer'
  | 'stop' | 'menu' | 'arrow-right' | 'arrow-left' | 'flask' | 'target' | 'volume' | 'link' | 'database' | 'cpu';

const stroke = (d: string, key?: string): ReactNode => <path key={key ?? d} d={d} />;

const GLYPHS: Record<IconName, ReactNode> = {
  plus: stroke('M12 5v14M5 12h14'),
  layers: <>{stroke('M12 3.5l9 4.8-9 4.8-9-4.8z')}{stroke('M3 12.6l9 4.8 9-4.8')}{stroke('M3 16.8l9 4.7 9-4.7')}</>,
  gauge: <>{stroke('M4.2 17.5a8.6 8.6 0 1 1 15.6 0')}{stroke('M12 14.5l4-5')}<circle cx="12" cy="14.8" r="1.3" /></>,
  gantt: <><rect x="3" y="5" width="10" height="3.6" rx="1" /><rect x="8" y="10.2" width="13" height="3.6" rx="1" /><rect x="5" y="15.4" width="9" height="3.6" rx="1" /></>,
  flag: <>{stroke('M5.5 21V4')}{stroke('M5.5 4.5h11.2l-2.2 4 2.2 4H5.5')}</>,
  chart: <>{stroke('M3.5 3.5v17h17')}{stroke('M7.5 15.5l3.8-5 3 3 4.7-6')}</>,
  text: stroke('M4 6.5h16M4 11h16M4 15.5h10M4 20h13'),
  ruler: <><rect x="2.5" y="8" width="19" height="8.5" rx="1.2" />{stroke('M6.5 8v3.2M10 8v4.6M13.5 8v3.2M17 8v4.6')}</>,
  sliders: <>{stroke('M6 3.5v6M6 14.5v6M12 3.5v2M12 10.5v10M18 3.5v10M18 18v2.5')}<circle cx="6" cy="12" r="2.3" /><circle cx="12" cy="8" r="2.3" /><circle cx="18" cy="15.5" r="2.3" /></>,
  help: <><circle cx="12" cy="12" r="9" />{stroke('M9.4 9.6a2.7 2.7 0 0 1 5.2.9c0 1.8-2.6 2.2-2.6 4')}{stroke('M12 17.2h.01')}</>,
  sun: <><circle cx="12" cy="12" r="3.8" />{stroke('M12 2.8v2M12 19.2v2M2.8 12h2M19.2 12h2M5.5 5.5l1.4 1.4M17.1 17.1l1.4 1.4M5.5 18.5l1.4-1.4M17.1 6.9l1.4-1.4')}</>,
  moon: stroke('M20 14.2A8 8 0 1 1 9.8 4a6.6 6.6 0 0 0 10.2 10.2z'),
  monitor: <><rect x="3" y="4" width="18" height="12.5" rx="2" />{stroke('M8.5 20.5h7M12 16.5v4')}</>,
  'chevron-left': stroke('M14.5 6l-6 6 6 6'),
  'chevron-right': stroke('M9.5 6l6 6-6 6'),
  'chevron-up': stroke('M6 14.5l6-6 6 6'),
  'chevron-down': stroke('M6 9.5l6 6 6-6'),
  play: <path d="M7.5 4.8l11 7.2-11 7.2z" fill="currentColor" />,
  pause: <><rect x="6" y="4.8" width="4" height="14.4" rx="1" fill="currentColor" /><rect x="14" y="4.8" width="4" height="14.4" rx="1" fill="currentColor" /></>,
  'skip-back': <>{stroke('M6 5v14')}<path d="M19 5.2l-10 6.8 10 6.8z" /></>,
  'skip-forward': <>{stroke('M18 5v14')}<path d="M5 5.2l10 6.8-10 6.8z" /></>,
  loop: <>{stroke('M17 2.8l3 3-3 3')}{stroke('M20 5.8H8.5A4.5 4.5 0 0 0 4 10.3v.7')}{stroke('M7 21.2l-3-3 3-3')}{stroke('M4 18.2h11.5a4.5 4.5 0 0 0 4.5-4.5V13')}</>,
  search: <><circle cx="11" cy="11" r="6.5" />{stroke('M20.5 20.5l-4.9-4.9')}</>,
  command: stroke('M15 6v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3'),
  check: stroke('M5 12.5l4.5 4.5L19 7.5'),
  x: stroke('M6 6l12 12M18 6L6 18'),
  info: <><circle cx="12" cy="12" r="9" />{stroke('M12 11v5.2M12 7.8h.01')}</>,
  'alert-triangle': <>{stroke('M12 3.4l9.6 16.6H2.4z')}{stroke('M12 10v4.4M12 17.4h.01')}</>,
  'alert-circle': <><circle cx="12" cy="12" r="9" />{stroke('M12 7.6v5.2M12 16.2h.01')}</>,
  download: stroke('M12 3.5v11.5M7.5 10.6L12 15l4.5-4.4M4.5 19.5h15'),
  upload: stroke('M12 15.5V4M7.5 8.4L12 4l4.5 4.4M4.5 19.5h15'),
  copy: <><rect x="8.5" y="8.5" width="12" height="12" rx="2" />{stroke('M15.5 8.5V6.5a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2')}</>,
  external: stroke('M14 4h6v6M20 4l-9 9M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4'),
  trash: stroke('M4 7h16M9.5 7V4.5h5V7M6.2 7l.9 13h9.8l.9-13M10 11v6M14 11v6'),
  'panel-left': <><rect x="3" y="4" width="18" height="16" rx="2.4" />{stroke('M9.5 4v16')}</>,
  clock: <><circle cx="12" cy="12" r="9" />{stroke('M12 7v5.2l3.2 2')}</>,
  filter: stroke('M4 5h16l-6.2 7.6V19l-3.6-1.8v-4.6z'),
  sort: stroke('M8 4.5v15M4.8 16.3L8 19.5l3.2-3.2M16 19.5v-15M12.8 7.7L16 4.5l3.2 3.2'),
  eye: <>{stroke('M2.4 12s3.5-6.8 9.6-6.8S21.6 12 21.6 12s-3.5 6.8-9.6 6.8S2.4 12 2.4 12z')}<circle cx="12" cy="12" r="2.8" /></>,
  'eye-off': <>{stroke('M9.9 5.5A9.6 9.6 0 0 1 12 5.2c6.1 0 9.6 6.8 9.6 6.8a16 16 0 0 1-2.3 3.2M6.4 7.2A15.6 15.6 0 0 0 2.4 12s3.5 6.8 9.6 6.8a9.4 9.4 0 0 0 4-.9')}{stroke('M9.8 9.8a3 3 0 0 0 4.4 4.4M3.5 3.5l17 17')}</>,
  'zoom-in': <><circle cx="10.5" cy="10.5" r="6.5" />{stroke('M20 20l-4.9-4.9M10.5 7.8v5.4M7.8 10.5h5.4')}</>,
  'zoom-out': <><circle cx="10.5" cy="10.5" r="6.5" />{stroke('M20 20l-4.9-4.9M7.8 10.5h5.4')}</>,
  fit: stroke('M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5'),
  'g-fast': stroke('M5 6.5l5.5 5.5L5 17.5M12.5 6.5L18 12l-5.5 5.5'),
  'g-slow': stroke('M7 3.8h10M7 20.2h10M8 3.8c0 5 8 5.2 8 8.2s-8 3.2-8 8.2'),
  'g-pause': <>{stroke('M9 5.5v13M15 5.5v13')}</>,
  'g-quiet': <>{stroke('M4 10v4h3.2l4.3 3.4V6.6L7.2 10z')}{stroke('M15 10.4a2.6 2.6 0 0 1 0 3.2')}</>,
  'g-loud': <>{stroke('M3.5 10v4h3.2L11 17.4V6.6L6.7 10z')}{stroke('M14.5 9a4 4 0 0 1 0 6M17.4 6.4a8 8 0 0 1 0 11.2')}</>,
  'g-flat': stroke('M4 9.5h16M4 14.5h16'),
  'g-unstable': stroke('M3 12l3-6.5L9 18.5l3-13 3 13 3-6.5 3 0'),
  'g-clarity': <>{stroke('M4 9V6.5A2.5 2.5 0 0 1 6.5 4H9M15 4h2.5A2.5 2.5 0 0 1 20 6.5V9M20 15v2.5a2.5 2.5 0 0 1-2.5 2.5H15M9 20H6.5A2.5 2.5 0 0 1 4 17.5V15')}<circle cx="12" cy="12" r="1.8" /></>,
  mic: <><rect x="9" y="3" width="6" height="11" rx="3" />{stroke('M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5v3')}</>,
  'file-audio': <>{stroke('M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z')}{stroke('M14 3v5h5')}{stroke('M9.5 16.5v-4.2l4-.9v4.2')}<circle cx="8.6" cy="16.6" r="0.9" /><circle cx="12.6" cy="15.6" r="0.9" /></>,
  refresh: <>{stroke('M20 11.5A8 8 0 0 0 5.9 6.6M4 4v4.2h4.2')}{stroke('M4 12.5A8 8 0 0 0 18.1 17.4M20 20v-4.2h-4.2')}</>,
  'bar-chart': stroke('M5.5 20V10.5M12 20V4M18.5 20v-6.5'),
  hash: stroke('M5 9h14M5 15h14M10.2 4L8.4 20M15.6 4l-1.8 16'),
  'shield-check': <>{stroke('M12 3l7.5 2.8v6c0 4.7-3.2 7.9-7.5 9.2-4.3-1.3-7.5-4.5-7.5-9.2v-6z')}{stroke('M8.6 12l2.4 2.4 4.4-4.6')}</>,
  book: <>{stroke('M5 4.5h10.5A2.5 2.5 0 0 1 18 7v13H8a3 3 0 0 1-3-3z')}{stroke('M5 17a3 3 0 0 1 3-3h10')}</>,
  keyboard: <><rect x="2" y="6" width="20" height="12" rx="2.2" />{stroke('M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10')}</>,
  printer: <>{stroke('M7 8.2V3.8h10v4.4')}{stroke('M7 17H5.2a1.2 1.2 0 0 1-1.2-1.2v-5.4A1.2 1.2 0 0 1 5.2 9.2h13.6A1.2 1.2 0 0 1 20 10.4v5.4a1.2 1.2 0 0 1-1.2 1.2H17')}<rect x="7" y="13.6" width="10" height="6.6" rx="0.8" /></>,
  stop: <rect x="6" y="6" width="12" height="12" rx="1.8" fill="currentColor" />,
  menu: stroke('M4 7h16M4 12h16M4 17h16'),
  'arrow-right': stroke('M5 12h14M13 6l6 6-6 6'),
  'arrow-left': stroke('M19 12H5M11 6l-6 6 6 6'),
  flask: <>{stroke('M9.5 3.5h5M10.3 3.5v5.8L5 18.4A1.8 1.8 0 0 0 6.6 21h10.8a1.8 1.8 0 0 0 1.6-2.6l-5.3-9.1V3.5')}{stroke('M7.8 14.6h8.4')}</>,
  target: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="3.6" />{stroke('M12 1.8v3M12 19.2v3M1.8 12h3M19.2 12h3')}</>,
  volume: <>{stroke('M4 10v4h3.2l4.3 3.4V6.6L7.2 10z')}{stroke('M15 9.4a3.8 3.8 0 0 1 0 5.2M17.8 6.8a7.6 7.6 0 0 1 0 10.4')}</>,
  link: stroke('M10.2 13.8a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M13.8 10.2a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1'),
  database: <><ellipse cx="12" cy="6" rx="7.5" ry="2.8" />{stroke('M4.5 6v6c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V6M4.5 12v6c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-6')}</>,
  cpu: <><rect x="6" y="6" width="12" height="12" rx="2" /><rect x="9.5" y="9.5" width="5" height="5" rx="0.6" />{stroke('M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3')}</>,
};

export interface IconProps {
  name: IconName;
  size?: number;
  stroke?: number;
  className?: string;
  style?: CSSProperties;
  /** Accessible name. Without it the icon is decorative and hidden from assistive technology. */
  title?: string;
}

export function Icon({ name, size = 18, stroke: strokeWidth = 1.6, className, style, title }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      style={style}
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
    >
      {GLYPHS[name]}
    </svg>
  );
}

/**
 * The VAANI mark: a V made of two strokes that leave one point together. The left one is the reference, the right one is the delivery,
 * which drifts away and ends in the copper marker where the two have separated the most. (The favicon in index.html is the same drawing.)
 */
export function LogoMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect x="0.5" y="0.5" width="31" height="31" rx="8" fill="var(--surface-3)" stroke="var(--rule-strong)" />
      <path d="M16 25.5L7.6 7" fill="none" stroke="var(--ink)" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M16 25.5C17.4 19 21.4 12.6 25.4 8" fill="none" stroke="var(--brand)" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="25.6" cy="7.6" r="2.3" fill="var(--copper)" />
    </svg>
  );
}
