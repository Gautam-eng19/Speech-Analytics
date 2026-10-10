/** Number and time formatting. Display only: values are rounded for reading, never recomputed. */

export function fmtNum(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '-';
  return value.toFixed(decimals).replace(/^-0(\.0+)?$/, (m) => m.slice(1));
}

/** With an explicit sign (+3.2 / -3.2), using a true minus sign. */
export function fmtSigned(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '-';
  const text = Math.abs(value).toFixed(decimals);
  if (Number(text) === 0) return text;
  return `${value < 0 ? '−' : '+'}${text}`;
}

export function fmtLevel(db: number | null | undefined, decimals = 1): string {
  if (db === null || db === undefined || !Number.isFinite(db)) return '-';
  const text = Math.abs(db).toFixed(decimals);
  return db < 0 && Number(text) !== 0 ? `−${text}` : text;
}

/** m:ss.s for recordings under an hour, h:mm:ss.s above. */
export function fmtClock(seconds: number, decimals = 1): string {
  if (!Number.isFinite(seconds)) return '-';
  const negative = seconds < 0;
  const total = Math.abs(seconds);
  const factor = 10 ** decimals;
  const rounded = Math.round(total * factor) / factor;
  const h = Math.floor(rounded / 3600);
  const m = Math.floor((rounded % 3600) / 60);
  const s = rounded - h * 3600 - m * 60;
  const sec = s.toFixed(decimals).padStart(decimals ? 3 + decimals : 2, '0');
  const body = h > 0 ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
  return negative ? `−${body}` : body;
}

export function fmtSecondsPlain(seconds: number, decimals = 1): string {
  return `${fmtNum(seconds, decimals)} s`;
}

export function fmtDuration(seconds: number): string {
  if (!Number.isFinite(seconds)) return '-';
  if (seconds < 59.95) return `${seconds.toFixed(1)} s`;
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  return `${m} min ${String(total - m * 60).padStart(2, '0')} s`;
}

export function shortHash(hash: string | null | undefined, length = 10): string {
  if (!hash) return '-';
  return hash.length <= length ? hash : hash.slice(0, length);
}

export function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export function fmtDateTime(iso: string | number | Date): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '-';
  return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function fmtRelative(iso: string | number | Date, now = Date.now()): string {
  const diff = (now - new Date(iso).getTime()) / 1000;
  if (!Number.isFinite(diff)) return '-';
  if (diff < 45) return 'just now';
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  if (diff < 86400 * 14) return `${Math.round(diff / 86400)} d ago`;
  return fmtDateTime(iso);
}

export function titleCase(slug: string): string {
  const spaced = slug.replace(/[_-]+/g, ' ').trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
