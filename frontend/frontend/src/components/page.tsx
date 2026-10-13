import type { ReactNode } from 'react';
import type { AnalysisSource } from '@/api/types';
import { fmtNum, shortHash } from '@/lib/format';
import { Chip, CopyButton } from './ui';

/** Page-level building blocks shared by the analysis pages. Styles live in styles/pages.css. */

export function PageHead({ eyebrow, title, meta, actions }: { eyebrow?: ReactNode; title: ReactNode; meta?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page__head">
      <div className="page__heading">
        {eyebrow ? <div className="eyebrow page__eyebrow">{eyebrow}</div> : null}
        <h2 className="page__title">{title}</h2>
        {meta ? <div className="page__meta">{meta}</div> : null}
      </div>
      {actions ? <div className="page__actions">{actions}</div> : null}
    </header>
  );
}

/** A figure the way a printed report numbers them: label, title, optional note, then the picture. */
export function Figure({ no, title, note, actions, children, className = '' }: { no?: number | string; title: ReactNode; note?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <figure className={`figure ${className}`}>
      <figcaption className="figure__cap">
        <div className="figure__titles">
          {no !== undefined ? <span className="figure__no num">Fig. {no}</span> : null}
          <span className="figure__title">{title}</span>
          {note ? <span className="figure__note">{note}</span> : null}
        </div>
        {actions ? <div className="figure__actions">{actions}</div> : null}
      </figcaption>
      {children}
    </figure>
  );
}

/** Severity (0 to 1, from the backend) as a small bar and its exact value. */
export function SeverityBar({ value, label = 'Severity' }: { value: number; label?: string }) {
  const clamped = Math.max(0, Math.min(1, value));
  return (
    <span className="sev" title={`${label} ${fmtNum(value, 2)} of 1`}>
      <span className="sev__bar" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={1} aria-valuenow={value}>
        <i style={{ width: `${clamped * 100}%` }} />
      </span>
      <span className="num sev__value">{fmtNum(value, 2)}</span>
    </span>
  );
}

export function SourceChip({ source }: { source: AnalysisSource }) {
  if (source === 'sample') return <Chip tone="info" icon="flask">Synthetic sample</Chip>;
  if (source === 'upload') return <Chip tone="brand" icon="file-audio">Uploaded recording</Chip>;
  return <Chip icon="database">Stored result</Chip>;
}

/** A label with its value, used in the facts lists. */
export function Fact({ label, children, mono = true, hint }: { label: ReactNode; children: ReactNode; mono?: boolean; hint?: ReactNode }) {
  return (
    <div className="fact">
      <dt>{label}</dt>
      <dd className={mono ? 'num' : undefined}>{children}{hint ? <span className="fact__hint">{hint}</span> : null}</dd>
    </div>
  );
}

/** A long hash or id, shortened for reading with the whole value one click away. */
export function HashValue({ value, length = 12, what }: { value: string; length?: number; what: string }) {
  return (
    <span className="hash">
      <span className="num" title={value}>{shortHash(value, length)}</span>
      <CopyButton text={value} label={`Copy ${what}`} what={`${what[0]?.toUpperCase() ?? ''}${what.slice(1)} copied`} />
    </span>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <div className="eyebrow">{children}</div>;
}

/** Body text from the backend with its numbers set in the tabular face. The text itself is never altered. */
export function Prose({ text, small }: { text: string; small?: boolean }) {
  const parts = text.split(/(\d+(?:\.\d+)?)/);
  return (
    <p className={`prose ${small ? 'prose--small' : ''}`}>
      {parts.map((part, i) => (i % 2 === 1 ? <span key={i} className="prose__num">{part}</span> : part))}
    </p>
  );
}
