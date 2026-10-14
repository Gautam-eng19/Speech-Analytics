// Accessibility audit: runs axe-core (WCAG 2.1 A and AA rules) on every page, in both themes, in a real browser.
//
//   BASE_URL=http://127.0.0.1:8000 node scripts/a11y.mjs [name-filter]
//
// Needs a running server that serves the built dashboard (see scripts/screenshots.mjs). Exits with 1 when any violation is found.
import { chromium } from 'playwright-core';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createRequire } from 'node:module';

const base = process.env.BASE_URL ?? 'http://127.0.0.1:8000';
const filter = process.argv[2] ?? '';
const axeSource = readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8');

function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH ?? '/opt/pw-browsers';
  if (existsSync(root)) {
    for (const dir of readdirSync(root).filter((d) => /^chromium-\d+$/.test(d))) {
      const candidate = join(root, dir, 'chrome-linux', 'chrome');
      if (existsSync(candidate)) return candidate;
    }
  }
  return undefined;
}

const index = await (await fetch(`${base}/samples/index.json`)).json();
const byId = Object.fromEntries(index.samples.map((s) => [s.id, s.analysis_id]));
const sample = (id, view) => `#/a/${byId[id]}/${view}`;

const PAGES = [
  ['analyze', '#/'],
  ['library', '#/library'],
  ['custom', '#/custom'],
  ['overview', sample('hesitant-delivery', 'overview')],
  ['overview-clean', sample('clean-delivery', 'overview')],
  ['timeline', sample('mixed-flaws', 'timeline')],
  ['flaws', sample('hesitant-delivery', 'flaws')],
  ['flaw-detail', sample('mixed-flaws', 'flaws') + '/flaw_001'],
  ['signals', sample('mixed-flaws', 'signals')],
  ['transcript', sample('rushed-explanation', 'transcript')],
  ['baseline', sample('hesitant-delivery', 'baseline')],
  ['report', sample('mixed-flaws', 'report')],
  ['settings', '#/settings'],
  ['help', '#/help'],
];

// Interactive states: a page is only as accessible as its dialogs, menus and small-screen layouts.
const STATES = [
  ['palette open', sample('mixed-flaws', 'overview'), {}, async (page) => { await page.keyboard.press('Control+k'); await page.waitForSelector('.palette'); await page.keyboard.type('too'); }],
  ['shortcuts dialog', sample('mixed-flaws', 'overview'), {}, async (page) => { await page.keyboard.press('?'); await page.waitForSelector('.dialog'); }],
  ['timeline, finding selected', sample('mixed-flaws', 'timeline'), {}, async (page) => { await page.locator('.flawband').first().click(); }],
  ['timeline, zoomed', sample('mixed-flaws', 'timeline'), {}, async (page) => { await page.keyboard.press('+'); await page.keyboard.press('+'); }],
  ['sidebar collapsed', sample('mixed-flaws', 'overview'), {}, async (page) => { await page.keyboard.press('b'); }],
  ['custom, passage typed and recordings added', '#/custom', {}, async (page) => {
    await page.fill('#custom-text', 'Good morning, my dear friends. Today we begin our long journey together. First we study the signal, then we measure every word. A clear voice carries ideas across the room. Speak with steady pace, calm breath, and care. Thank you for listening to this talk.');
    const wav = Buffer.from('UklGRiQAAABXQVZFZm10IBAAAAABAAEAgLsAAAB3AQACABAAZGF0YQAAAAA=', 'base64');
    await page.setInputFiles('input[type=file][multiple]', [{ name: 'one.wav', mimeType: 'audio/wav', buffer: wav }, { name: 'two.wav', mimeType: 'audio/wav', buffer: wav }]);
    await page.waitForSelector('.take-list__item');
  }],
  ['custom, recorder', '#/custom', {}, async (page) => { await page.getByRole('radio', { name: 'Record now' }).first().click(); }],
  ['phone, custom', '#/custom', { width: 390, height: 844 }, async () => {}],
  ['recorder, idle', '#/', {}, async (page) => { await page.getByRole('radio', { name: 'Record now' }).click(); }],
  ['recorder, live', '#/', {}, async (page) => { await page.getByRole('radio', { name: 'Record now' }).click(); await page.getByRole('button', { name: 'Start recording' }).click(); await page.waitForSelector('.rec__live'); await page.waitForTimeout(900); }],
  ['recorder, take ready', '#/', {}, async (page) => { await page.getByRole('radio', { name: 'Record now' }).click(); await page.getByRole('button', { name: 'Start recording' }).click(); await page.waitForSelector('.rec__live'); await page.waitForTimeout(900); await page.getByRole('button', { name: 'Stop' }).click(); await page.waitForSelector('.rec__take'); }],
  ['phone, navigation drawer', '#/', { width: 390, height: 844 }, async (page) => { await page.getByRole('button', { name: 'Open navigation' }).click(); }],
  ['phone, overview', sample('hesitant-delivery', 'overview'), { width: 390, height: 844 }, async () => {}],
  ['phone, timeline', sample('mixed-flaws', 'timeline'), { width: 390, height: 844 }, async () => {}],
  ['phone, finding', sample('mixed-flaws', 'flaws') + '/flaw_001', { width: 390, height: 844 }, async () => {}],
];

// The browser is started with a fake microphone so the recorder can be exercised without hardware.
const browser = await chromium.launch({ executablePath: findChrome(), args: ['--no-sandbox', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
let total = 0;

async function audit(page, theme, name) {
  await page.evaluate(axeSource);
  const result = await page.evaluate(() => globalThis.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } }));
  total += result.violations.length;
  console.log(`${result.violations.length === 0 ? 'ok  ' : 'FAIL'} ${theme.padEnd(5)} ${name}  (${result.passes.length} rules passed)`);
  for (const v of result.violations) {
    console.log(`      ${v.impact} · ${v.id}: ${v.help} (${v.nodes.length})`);
    for (const node of v.nodes.slice(0, 3)) console.log(`        ${node.target.join(' ')}  ${node.failureSummary?.split('\n')[1]?.trim() ?? ''}`);
  }
}

for (const theme of ['light', 'dark']) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: theme, permissions: ['microphone'] });
  await context.addInitScript((t) => { try { localStorage.setItem('sa.settings.v1', JSON.stringify({ theme: t })); } catch {} }, theme);
  const page = await context.newPage();
  for (const [name, hash] of PAGES) {
    if (filter && !name.includes(filter)) continue;
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${base}/${hash}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(500);
    await audit(page, theme, name);
  }
  for (const [name, hash, viewport, act] of STATES) {
    if (filter && !name.includes(filter)) continue;
    await page.setViewportSize({ width: viewport.width ?? 1440, height: viewport.height ?? 900 });
    await page.goto('about:blank'); // a fresh load: no overlay from the previous state may stay open
    await page.goto(`${base}/${hash}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);
    await act(page);
    await page.waitForTimeout(350);
    await audit(page, theme, name);
    await page.evaluate(() => localStorage.setItem('sa.settings.v1', JSON.stringify({ theme: document.documentElement.dataset.theme })));
  }
  await context.close();
}
await browser.close();
console.log(total === 0 ? '\nNo violations.' : `\n${total} violation(s).`);
process.exit(total === 0 ? 0 : 1);
