import type { Flaw } from '@/api/types';
import { findingsCsv } from '@/lib/csv';
import { settingsStore, resolveTheme, updateSettings } from '@/lib/settings';
import { adjacentFlaw, flawsByTime, recordingDuration } from '@/lib/result';
import { windowAround } from '@/lib/time';
import { analysisStore } from './analysis';
import { playerStore, playheadStore, playRange, seek, toggle } from './player';
import { pushToast, selectFlaw, selectionStore, setView } from './ui';

/** Things the user can do from several places (buttons, shortcuts, the command palette). One implementation each. */

export function goToFlaw(flaw: Flaw, options: { play?: boolean; loop?: boolean } = {}): void {
  const current = analysisStore.get().current;
  if (!current) return;
  selectFlaw(flaw.flaw_id);
  setView(windowAround(flaw.start_s, flaw.end_s, recordingDuration(current.result), 1.1));
  if (playerStore.get().src) {
    if (options.play) playRange(flaw.start_s, flaw.end_s, options.loop ?? false);
    else seek(flaw.start_s);
  }
}

/** Move the selection to the next or previous flaw in time order (starting from the selection, else from the playhead). */
export function stepFlaw(direction: 1 | -1): void {
  const current = analysisStore.get().current;
  if (!current) return;
  const ordered = flawsByTime(current.result.flaws);
  if (ordered.length === 0) {
    pushToast('This analysis has no findings to step through.', 'info', 2200);
    return;
  }
  const selected = ordered.findIndex((f) => f.flaw_id === selectionStore.get().flawId);
  let target: Flaw | null = null;
  if (selected >= 0) target = ordered[selected + direction] ?? null;
  else target = adjacentFlaw(ordered, playheadStore.get(), direction);
  if (!target) {
    pushToast(direction === 1 ? 'That is the last finding.' : 'That is the first finding.', 'info', 1800);
    return;
  }
  goToFlaw(target, { play: playerStore.get().playing });
}

export function togglePlayback(): void {
  if (!playerStore.get().src) {
    pushToast('There is no audio for this analysis. Uploads are analysed but not stored, so only the data can be shown.', 'info', 4200);
    return;
  }
  toggle();
}

export function setTheme(theme: 'system' | 'light' | 'dark'): void {
  updateSettings({ theme });
}

/** Quick toggle: switch between light and dark, based on what is showing now. */
export function toggleTheme(): void {
  const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const showing = resolveTheme(settingsStore.get().theme, systemDark);
  updateSettings({ theme: showing === 'dark' ? 'light' : 'dark' });
}

export function toggleSidebar(): void {
  updateSettings({ sidebarCollapsed: !settingsStore.get().sidebarCollapsed });
}

function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function fileStem(): { stem: string; id: string } | null {
  const current = analysisStore.get().current;
  if (!current) return null;
  const safe = current.title.replace(/[^\w.-]+/g, '_').replace(/_+/g, '_').slice(0, 48) || 'analysis';
  return { stem: safe, id: current.result.analysis_id.slice(0, 8) };
}

/** The result exactly as the API returned it (reproducible evidence; nothing is added). */
export function exportResultJson(): void {
  const current = analysisStore.get().current;
  const name = fileStem();
  if (!current || !name) return;
  download(new Blob([JSON.stringify(current.result, null, 2)], { type: 'application/json' }), `${name.stem}.${name.id}.json`);
  pushToast('Result saved as JSON.', 'success', 2200);
}

/** The findings as a spreadsheet table (one row each, backend values unrounded). */
export function exportFindingsCsv(): void {
  const current = analysisStore.get().current;
  const name = fileStem();
  if (!current || !name) return;
  if (current.result.flaws.length === 0) {
    pushToast('This analysis has no findings to export.', 'info', 2600);
    return;
  }
  download(new Blob([findingsCsv(current.result)], { type: 'text/csv;charset=utf-8' }), `${name.stem}.${name.id}.findings.csv`);
  pushToast('Findings saved as CSV.', 'success', 2200);
}

/** A link to the page that is showing. It opens the same analysis for anyone who can reach the same server. */
export async function copyPageLink(): Promise<void> {
  try {
    await navigator.clipboard.writeText(window.location.href);
    pushToast('Link copied to the clipboard.', 'success', 2000);
  } catch {
    pushToast('The browser did not allow copying. The address bar has the link.', 'error');
  }
}
