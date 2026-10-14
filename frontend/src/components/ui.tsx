import { useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Icon, type IconName } from './Icon';
import { flawColor, flawMeta } from '@/lib/flawMeta';
import { useStore } from '@/lib/store';
import { dismissToast, pushToast, toastStore } from '@/state/ui';

/** Small shared building blocks. Styles live in styles/components.css. */

// ---- buttons ---------------------------------------------------------------------------------------------------------------
type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  icon?: IconName;
  iconRight?: IconName;
  size?: 'sm' | 'md' | 'lg';
  busy?: boolean;
}

export function Button({ variant = 'secondary', icon, iconRight, size = 'md', busy, className = '', children, disabled, ...rest }: ButtonProps) {
  return (
    <button type="button" className={`btn btn--${variant} btn--${size} ${className}`} disabled={disabled || busy} aria-busy={busy || undefined} {...rest}>
      {busy ? <span className="spinner" aria-hidden="true" /> : icon ? <Icon name={icon} size={size === 'sm' ? 15 : size === 'lg' ? 18 : 16} /> : null}
      {children ? <span className="btn__label">{children}</span> : null}
      {iconRight ? <Icon name={iconRight} size={size === 'lg' ? 17 : 15} /> : null}
    </button>
  );
}

export function IconButton({ icon, label, className = '', size = 18, active, ...rest }: { icon: IconName; label: string; size?: number; active?: boolean } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" className={`icon-btn ${active ? 'is-active' : ''} ${className}`} aria-label={label} title={label} aria-pressed={active} {...rest}>
      <Icon name={icon} size={size} />
    </button>
  );
}

// ---- tooltip (CSS driven; shows on hover and keyboard focus) -------------------------------------------------------------------
export function Tip({ text, side = 'top', children }: { text: ReactNode; side?: 'top' | 'right' | 'bottom'; children: ReactNode }) {
  return (
    <span className={`tip tip--${side}`}>
      {children}
      <span className="tip__bubble" role="tooltip">{text}</span>
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}

// ---- panel -------------------------------------------------------------------------------------------------------------------
export function Panel({ title, eyebrow, actions, children, className = '', flush }: { title?: ReactNode; eyebrow?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; flush?: boolean }) {
  return (
    <section className={`panel ${className}`}>
      {title || eyebrow || actions ? (
        <header className="panel__head">
          <div className="panel__titles">
            {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
            {title ? <h2 className="panel__title">{title}</h2> : null}
          </div>
          {actions ? <div className="panel__actions">{actions}</div> : null}
        </header>
      ) : null}
      <div className={flush ? 'panel__body panel__body--flush' : 'panel__body'}>{children}</div>
    </section>
  );
}

/** A scrollable block (a wide table) that keyboard users can focus and scroll. */
export function ScrollRegion({ label, children, className = '' }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div className={`table-scroll ${className}`} role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}

// ---- chips and tags ------------------------------------------------------------------------------------------------------------
export function Chip({ children, tone = 'neutral', icon }: { children: ReactNode; tone?: 'neutral' | 'brand' | 'good' | 'warn' | 'bad' | 'info'; icon?: IconName }) {
  return (
    <span className={`chip chip--${tone}`}>
      {icon ? <Icon name={icon} size={12} /> : null}
      {children}
    </span>
  );
}

/** A flaw type: glyph + name, tinted with the type's colour. Never colour alone. */
export function FlawTag({ type, compact }: { type: string; compact?: boolean }) {
  const meta = flawMeta(type);
  return (
    <span className="flaw-tag" style={{ ['--c' as string]: flawColor(type) }} title={meta.definition}>
      <Icon name={meta.icon} size={compact ? 13 : 14} />
      {compact ? null : <span>{meta.label}</span>}
    </span>
  );
}

// ---- meter ---------------------------------------------------------------------------------------------------------------------
/** A 0-100 scale. `value` is the backend's number; the bar is only its picture. */
export function Meter({ value, label, tone }: { value: number; label: string; tone?: 'brand' | 'warn' | 'bad' }) {
  return (
    <div className={`meter ${tone ? `meter--${tone}` : ''}`} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value} aria-label={label}>
      <div className="meter__fill" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      <div className="meter__ticks" aria-hidden="true">
        {[25, 50, 75].map((t) => <i key={t} style={{ left: `${t}%` }} />)}
      </div>
    </div>
  );
}

// ---- segmented control -------------------------------------------------------------------------------------------------------------
export function Segmented<T extends string>({ value, onChange, options, label, size = 'md' }: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label?: string; icon?: IconName; title?: string }[];
  label: string;
  size?: 'sm' | 'md';
}) {
  return (
    <div className={`seg seg--${size}`} role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={o.value === value} className={o.value === value ? 'is-on' : ''} title={o.title ?? o.label} aria-label={o.title ?? o.label} onClick={() => onChange(o.value)}>
          {o.icon ? <Icon name={o.icon} size={size === 'sm' ? 14 : 15} /> : null}
          {o.label ? <span>{o.label}</span> : null}
        </button>
      ))}
    </div>
  );
}

/** A pill that is either on or off (lane visibility, filters). */
export function ToggleChip({ on, onChange, children, icon, title }: { on: boolean; onChange: (on: boolean) => void; children: ReactNode; icon?: IconName; title?: string }) {
  return (
    <button type="button" className={`toggle-chip ${on ? 'is-on' : ''}`} aria-pressed={on} title={title} onClick={() => onChange(!on)}>
      {icon ? <Icon name={icon} size={13} /> : null}
      {children}
    </button>
  );
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (checked: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} className={`switch ${checked ? 'is-on' : ''}`} onClick={() => onChange(!checked)}>
      <span className="switch__thumb" />
    </button>
  );
}

// ---- states --------------------------------------------------------------------------------------------------------------------------
export function EmptyState({ icon, title, children, action }: { icon: IconName; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty__icon"><Icon name={icon} size={22} /></div>
      <h3 className="empty__title">{title}</h3>
      {children ? <p className="empty__text">{children}</p> : null}
      {action ? <div className="empty__action">{action}</div> : null}
    </div>
  );
}

export function Skeleton({ width = '100%', height = 14, radius = 4 }: { width?: number | string; height?: number | string; radius?: number }) {
  return <span className="skeleton" style={{ width, height, borderRadius: radius }} aria-hidden="true" />;
}

// ---- copy ---------------------------------------------------------------------------------------------------------------------------------
export function CopyButton({ text, label = 'Copy', what = 'Copied' }: { text: string; label?: string; what?: string }) {
  const [done, setDone] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      pushToast(`${what} to the clipboard.`, 'success', 1800);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setDone(false), 1500);
    } catch {
      pushToast('The browser did not allow copying.', 'error');
    }
  };
  return <IconButton icon={done ? 'check' : 'copy'} label={label} size={15} onClick={copy} className="icon-btn--small" />;
}

// ---- modal dialog -------------------------------------------------------------------------------------------------------------------
export function Dialog({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current;
    node?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
      if (e.key === 'Tab' && node) {
        const focusable = node.querySelectorAll<HTMLElement>('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        if (focusable.length === 0) return;
        const first = focusable[0]!;
        const last = focusable[focusable.length - 1]!;
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      previous?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} className={`dialog ${wide ? 'dialog--wide' : ''}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <header className="dialog__head">
          <h2 className="dialog__title">{title}</h2>
          <IconButton icon="x" label="Close" onClick={onClose} />
        </header>
        <div className="dialog__body" tabIndex={0}>{children}</div>
      </div>
    </div>,
    document.body,
  );
}

// ---- toasts --------------------------------------------------------------------------------------------------------------------------------
export function Toasts() {
  const toasts = useStore(toastStore, (s) => s);
  return (
    <div className="toasts no-print" aria-live="polite" aria-atomic="false">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast--${t.kind}`} role="status">
          <Icon name={t.kind === 'error' ? 'alert-circle' : t.kind === 'success' ? 'check' : 'info'} size={16} />
          <span>{t.message}</span>
          <button type="button" className="toast__close" aria-label="Dismiss" onClick={() => dismissToast(t.id)}><Icon name="x" size={14} /></button>
        </div>
      ))}
    </div>
  );
}
