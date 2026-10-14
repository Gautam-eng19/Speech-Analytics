import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '@/app/App';
import { DEFAULT_SETTINGS, settingsStore } from '@/lib/settings';
import { closeAnalysis } from '@/state/analysis';
import { clearHistory } from '@/state/history';
import { overlayStore, selectionStore } from '@/state/ui';
import { hesitantResult } from './fixtures';
import { stubFetch, stubLayout } from './helpers';

async function openApp(hash: string) {
  window.location.hash = hash;
  let utils!: ReturnType<typeof render>;
  await act(async () => { utils = render(<App />); });
  return utils;
}

/** The list of results inside the open command palette (the playback-speed menu has options too, so scope to the palette). */
const palette = async () => (await screen.findByRole('dialog', { name: /Search and jump/ })).querySelector('#palette-list') as HTMLElement;

describe('App (routing, loading, keyboard)', () => {
  beforeEach(() => {
    stubLayout(900);
    stubFetch();
    closeAnalysis();
    clearHistory();
    settingsStore.set({ ...DEFAULT_SETTINGS });
    selectionStore.set({ flawId: null });
    overlayStore.set({ palette: false, shortcuts: false, mobileNav: false });
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it('starts on the new-analysis page with the analysis views disabled', async () => {
    await openApp('');
    expect(await screen.findByRole('heading', { level: 1, name: /Hear the difference/ })).toBeInTheDocument();
    expect(screen.getByText('Open an analysis to enable these views.')).toBeInTheDocument();
  });

  it('opens a demo sample from its address, without any API call for its result', async () => {
    const { calls } = stubFetch();
    await openApp(`#/a/${hesitantResult.analysis_id}/overview`);
    expect(await screen.findByRole('heading', { level: 2, name: 'Hesitant delivery' })).toBeInTheDocument();
    expect(screen.getByText('Open analysis')).toBeInTheDocument();
    expect(calls.some((url) => url.includes('/api/v1/result/'))).toBe(false);
  });

  it('reads an analysis that is not a sample from the API', async () => {
    const { calls } = stubFetch({ '/api/v1/result/stored-1': () => new Response(JSON.stringify({ ...hesitantResult, analysis_id: 'stored-1' }), { headers: { 'Content-Type': 'application/json' } }) });
    await openApp('#/a/stored-1/overview');
    expect(await screen.findByRole('heading', { level: 2, name: 'Analysis stored-1' })).toBeInTheDocument();
    expect(calls.some((url) => url.endsWith('/api/v1/result/stored-1'))).toBe(true);
    // An analysis fetched by id has no audio: the playback bar must not appear.
    expect(document.querySelector('.transport')).toBeNull();
  });

  it('says clearly when the analysis does not exist, and keeps the chrome of the open analysis out of it', async () => {
    await openApp(`#/a/${hesitantResult.analysis_id}/overview`);
    await screen.findByRole('heading', { level: 2, name: 'Hesitant delivery' });
    expect(document.querySelector('.ribbon')).not.toBeNull();
    await act(async () => { window.location.hash = '#/a/missing/overview'; });
    expect(await screen.findByText('This analysis is not available')).toBeInTheDocument();
    expect(document.querySelector('.ribbon')).toBeNull();
    expect(document.querySelector('.transport')).toBeNull();
  });

  it('keeps the browser tab title in step with the page and the open analysis', async () => {
    await openApp('');
    await screen.findByRole('heading', { level: 1, name: /Hear the difference/ });
    expect(document.title).toBe('VAANI · Contrastive speech analytics');
    await act(async () => { window.location.hash = `#/a/${hesitantResult.analysis_id}/timeline`; });
    await screen.findByRole('toolbar', { name: 'Timeline controls' });
    await waitFor(() => expect(document.title).toBe('Timeline · Hesitant delivery · VAANI'));
    await act(async () => { window.location.hash = '#/settings'; });
    await waitFor(() => expect(document.title).toBe('Settings · VAANI'));
  });

  it('closes the phone navigation drawer when the page changes by any route, and on Escape', async () => {
    await openApp('');
    await screen.findByRole('heading', { level: 1, name: /Hear the difference/ });
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    expect(overlayStore.get().mobileNav).toBe(true);
    await act(async () => { window.location.hash = '#/library'; });
    await waitFor(() => expect(overlayStore.get().mobileNav).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'Open navigation' }));
    expect(overlayStore.get().mobileNav).toBe(true);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(overlayStore.get().mobileNav).toBe(false);
  });

  it('shows a page-not-found message for an unknown address', async () => {
    await openApp('#/definitely/not/a/page');
    expect(await screen.findByRole('heading', { level: 3, name: 'Page not found' })).toBeInTheDocument();
  });

  it('switches views with the number keys', async () => {
    await openApp(`#/a/${hesitantResult.analysis_id}/overview`);
    await screen.findByRole('heading', { level: 2, name: 'Hesitant delivery' });
    fireEvent.keyDown(window, { key: '3' });
    await waitFor(() => expect(window.location.hash).toBe(`#/a/${hesitantResult.analysis_id}/flaws`));
    expect(await screen.findByRole('heading', { level: 2, name: /findings?/ })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: '6' });
    await waitFor(() => expect(window.location.hash).toMatch(/\/baseline$/));
    expect(await screen.findByRole('heading', { level: 2, name: 'Baseline and method' })).toBeInTheDocument();
  });

  it('does not react to shortcut keys while typing in a field', async () => {
    await openApp(`#/a/${hesitantResult.analysis_id}/overview`);
    await screen.findByRole('heading', { level: 2, name: 'Hesitant delivery' });
    const field = document.createElement('input');
    document.body.appendChild(field);
    field.focus();
    fireEvent.keyDown(field, { key: '3' });
    fireEvent.keyDown(field, { key: 't' });
    expect(window.location.hash).toMatch(/\/overview$/);
    expect(settingsStore.get().theme).toBe('dark');
    field.remove();
  });

  it('toggles the theme with t and applies it to the document', async () => {
    await openApp('');
    await screen.findByRole('heading', { level: 1, name: /Hear the difference/ });
    const before = document.documentElement.dataset.theme;
    fireEvent.keyDown(window, { key: 't' });
    await waitFor(() => expect(document.documentElement.dataset.theme).not.toBe(before));
    expect(['light', 'dark']).toContain(document.documentElement.dataset.theme);
    expect(localStorage.getItem('sa.settings.v1')).toContain('"theme"');
  });

  it('collapses the sidebar with b and remembers it', async () => {
    await openApp('');
    await screen.findByRole('heading', { level: 1, name: /Hear the difference/ });
    fireEvent.keyDown(window, { key: 'b' });
    await waitFor(() => expect(document.querySelector('.app')!.getAttribute('data-collapsed')).toBe('true'));
    expect(settingsStore.get().sidebarCollapsed).toBe(true);
  });

  it('goes to a page with the g chord', async () => {
    await openApp('');
    await screen.findByRole('heading', { level: 1, name: /Hear the difference/ });
    fireEvent.keyDown(window, { key: 'g' });
    fireEvent.keyDown(window, { key: 'l' });
    await waitFor(() => expect(window.location.hash).toBe('#/library'));
  });

  it('opens the shortcut list with ? and closes it with Escape', async () => {
    await openApp('');
    await screen.findByRole('heading', { level: 1, name: /Hear the difference/ });
    fireEvent.keyDown(window, { key: '?' });
    expect(await screen.findByRole('dialog', { name: 'Keyboard shortcuts' })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).toBeNull());
  });

  it('opens the command palette with Ctrl+K, filters, and runs the chosen command', async () => {
    await openApp(`#/a/${hesitantResult.analysis_id}/overview`);
    await screen.findByRole('heading', { level: 2, name: 'Hesitant delivery' });
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const box = await screen.findByRole('combobox', { name: 'Search' });
    fireEvent.change(box, { target: { value: 'signals' } });
    const options = await within(await palette()).findAllByRole('option');
    expect(options[0]).toHaveTextContent('Signals');
    fireEvent.keyDown(screen.getByRole('dialog', { name: /Search and jump/ }), { key: 'Enter' });
    await waitFor(() => expect(window.location.hash).toMatch(/\/signals$/));
  });

  it('lists the findings of the open analysis in the palette', async () => {
    await openApp(`#/a/${hesitantResult.analysis_id}/overview`);
    await screen.findByRole('heading', { level: 2, name: 'Hesitant delivery' });
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const box = await screen.findByRole('combobox', { name: 'Search' });
    fireEvent.change(box, { target: { value: 'excessive pause' } });
    const options = await within(await palette()).findAllByRole('option');
    expect(options.length).toBe(hesitantResult.flaws.filter((f) => f.type === 'excessive_pause').length);
  });
});
