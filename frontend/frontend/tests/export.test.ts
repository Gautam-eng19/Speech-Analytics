import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { csvField, findingsCsv, toCsv } from '@/lib/csv';
import { analysisStore, closeAnalysis } from '@/state/analysis';
import { copyPageLink, exportFindingsCsv } from '@/state/actions';
import { toastStore } from '@/state/ui';
import { cleanResult, loaded, mixedResult } from './fixtures';

/** A small RFC 4180 reader, so the tests check what a spreadsheet would see. */
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  const body = text.replace(/^﻿/, '');
  for (let i = 0; i < body.length; i++) {
    const c = body[i]!;
    if (quoted) {
      if (c === '"' && body[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { row.push(field); field = ''; }
    else if (c === '\r' && body[i + 1] === '\n') { row.push(field); rows.push(row); row = []; field = ''; i++; }
    else field += c;
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row); }
  return rows;
}

describe('csvField and toCsv', () => {
  it('quotes only where needed and doubles quotes', () => {
    expect(csvField('plain')).toBe('plain');
    expect(csvField('a,b')).toBe('"a,b"');
    expect(csvField('say "hi"')).toBe('"say ""hi"""');
    expect(csvField('two\nlines')).toBe('"two\nlines"');
  });
  it('writes numbers, booleans and gaps', () => {
    expect(csvField(4.8344)).toBe('4.8344');
    expect(csvField(false)).toBe('false');
    expect(csvField(null)).toBe('');
    expect(csvField(undefined)).toBe('');
  });
  it('separates rows with CRLF and ends with one', () => {
    expect(toCsv([['a', 'b'], ['c,d', 'e']])).toBe('a,b\r\n"c,d",e\r\n');
  });
});

describe('findingsCsv', () => {
  const text = findingsCsv(mixedResult);
  const rows = parseCsv(text);
  const header = rows[0]!;
  const col = (name: string) => header.indexOf(name);

  it('starts with a byte-order mark so a spreadsheet reads the typography correctly', () => {
    expect(text.charCodeAt(0)).toBe(0xfeff);
  });
  it('has one row per finding, in time order, under a header', () => {
    expect(rows).toHaveLength(mixedResult.flaws.length + 1);
    const starts = rows.slice(1).map((r) => Number(r[col('start_s')]));
    expect(starts).toEqual([...starts].sort((a, b) => a - b));
  });
  it('keeps every number exactly as the backend returned it', () => {
    const rate = mixedResult.flaws.find((f) => f.type === 'too_fast')!;
    const row = rows.slice(1).find((r) => r[col('flaw_id')] === rate.flaw_id)!;
    expect(row[col('severity')]).toBe(String(rate.severity));
    expect(row[col('evidence.rate_z_score')]).toBe(String((rate.evidence as { rate_z_score: number }).rate_z_score));
    expect(row[col('evidence.rate_participant_wpm')]).toBe('197.3868');
    expect(row[col('rule_threshold_z')]).toBe(String(rate.rule!.threshold_z));
  });
  it('flattens the evidence of every type into columns and leaves the others empty', () => {
    expect(header).toContain('evidence.rate_z_score');
    expect(header).toContain('evidence.pause_z_score');
    const pause = mixedResult.flaws.find((f) => f.type === 'excessive_pause')!;
    const row = rows.slice(1).find((r) => r[col('flaw_id')] === pause.flaw_id)!;
    expect(row[col('evidence.pause_z_score')]).not.toBe('');
    expect(row[col('evidence.rate_z_score')]).toBe('');
  });
  it('round-trips the explanation and recommendation text, quotes and commas included', () => {
    for (const f of mixedResult.flaws) {
      const row = rows.slice(1).find((r) => r[col('flaw_id')] === f.flaw_id)!;
      expect(row[col('explanation')]).toBe(f.explanation);
      expect(row[col('recommendation')]).toBe(f.recommendation);
      expect(row[col('affected_words')]).toBe((f.affected_words ?? []).join(' '));
    }
  });
  it('has only the header when there are no findings', () => {
    expect(parseCsv(findingsCsv({ ...cleanResult, flaws: [] }))).toHaveLength(1);
  });
});

describe('export actions', () => {
  beforeEach(() => { toastStore.set([]); closeAnalysis(); });
  afterEach(() => vi.restoreAllMocks());

  function captureDownloads() {
    const names: string[] = [];
    const blobs: Blob[] = [];
    vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => { blobs.push(blob as Blob); return 'blob:x'; });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download); });
    return { names, blobs };
  }
  const readBytes = (blob: Blob) => new Promise<Uint8Array>((resolve) => { const r = new FileReader(); r.onload = () => resolve(new Uint8Array(r.result as ArrayBuffer)); r.readAsArrayBuffer(blob); });

  it('saves the findings as a CSV named after the analysis', async () => {
    analysisStore.set({ status: 'ready', current: loaded(mixedResult), progress: null, error: null });
    const { names, blobs } = captureDownloads();
    exportFindingsCsv();
    expect(names).toEqual([`Mixed_flaws.${mixedResult.analysis_id.slice(0, 8)}.findings.csv`]);
    expect(blobs[0]!.type).toContain('text/csv');
    const bytes = await readBytes(blobs[0]!);
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]); // the UTF-8 byte-order mark
    expect(new TextDecoder().decode(bytes)).toBe(findingsCsv(mixedResult).slice(1));
    expect(toastStore.get().some((t) => t.message === 'Findings saved as CSV.')).toBe(true);
  });
  it('says so, and saves nothing, when there is nothing to export', () => {
    analysisStore.set({ status: 'ready', current: loaded({ ...cleanResult, flaws: [] }), progress: null, error: null });
    const { names } = captureDownloads();
    exportFindingsCsv();
    expect(names).toEqual([]);
    expect(toastStore.get().some((t) => /no findings to export/.test(t.message))).toBe(true);
  });
  it('does nothing without an open analysis', () => {
    const { names } = captureDownloads();
    exportFindingsCsv();
    expect(names).toEqual([]);
    expect(toastStore.get()).toEqual([]);
  });
  it('copies the address of the page, and says when the browser refuses', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    window.location.hash = '#/a/abc/timeline';
    await copyPageLink();
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('#/a/abc/timeline'));
    expect(toastStore.get().at(-1)!.kind).toBe('success');
    writeText.mockRejectedValue(new Error('denied'));
    await copyPageLink();
    expect(toastStore.get().at(-1)!.kind).toBe('error');
  });
});
