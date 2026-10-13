// Visual QA: render dashboard pages in a real browser, in both themes and two sizes, and save PNGs.
//
//   BASE_URL=http://127.0.0.1:8000 OUT_DIR=shots node scripts/screenshots.mjs [name-filter]
//
// Needs a running server that serves the built dashboard (`npm run build`, then
// `python -m uvicorn app.main:app --app-dir backend`) and a Chromium: CHROME_PATH, or Playwright's own.
import { chromium } from 'playwright-core';
import { mkdirSync, existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const base = process.env.BASE_URL ?? 'http://127.0.0.1:8000';
const out = process.env.OUT_DIR ?? 'shots';
const filter = process.argv[2] ?? '';

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

const SHOTS = [
  { name: 'analyze', hash: '#/' },
  { name: 'library', hash: '#/library' },
  { name: 'overview', hash: sample('hesitant-delivery', 'overview') },
  { name: 'overview-clean', hash: sample('clean-delivery', 'overview') },
  { name: 'timeline', hash: sample('mixed-flaws', 'timeline'), settle: 900 },
  { name: 'flaws', hash: sample('hesitant-delivery', 'flaws') },
  { name: 'flaw-detail', hash: sample('mixed-flaws', 'flaws') + '/flaw_001' },
  { name: 'signals', hash: sample('mixed-flaws', 'signals'), settle: 700 },
  { name: 'transcript', hash: sample('rushed-explanation', 'transcript') },
  { name: 'baseline', hash: sample('hesitant-delivery', 'baseline') },
  { name: 'report', hash: sample('mixed-flaws', 'report') },
  { name: 'settings', hash: '#/settings' },
  { name: 'help', hash: '#/help' },
];

const SIZES = {
  desktop: { width: 1440, height: 900 },
  tall: { width: 1440, height: 1500 },
  phone: { width: 390, height: 844, deviceScaleFactor: 2, isMobile: true },
};

mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ executablePath: findChrome(), args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required'] });

for (const theme of ['light', 'dark']) {
  for (const [sizeName, viewport] of Object.entries(SIZES)) {
    const context = await browser.newContext({ viewport, deviceScaleFactor: viewport.deviceScaleFactor ?? 1, isMobile: viewport.isMobile ?? false, colorScheme: theme });
    await context.addInitScript((t) => {
      try { localStorage.setItem('sa.settings.v1', JSON.stringify({ theme: t })); } catch {}
    }, theme);
    const page = await context.newPage();
    const problems = [];
    page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
    page.on('console', (m) => { if (m.type() === 'error') problems.push(`console: ${m.text()}`); });
    for (const shot of SHOTS) {
      if (filter && !shot.name.includes(filter)) continue;
      // desktop: the viewport shows the shell; tall: whole page content; phone: layout check on a subset
      if (sizeName === 'tall' && !['overview', 'flaws', 'baseline', 'signals', 'report', 'settings', 'help', 'library', 'analyze', 'transcript'].includes(shot.name)) continue;
      if (sizeName === 'phone' && !['analyze', 'overview', 'timeline', 'flaws'].includes(shot.name)) continue;
      await page.goto(`${base}/${shot.hash}`, { waitUntil: 'networkidle' });
      await page.waitForTimeout(shot.settle ?? 450);
      await page.screenshot({ path: join(out, `${shot.name}.${sizeName}.${theme}.png`) });
    }
    if (problems.length) console.log(`[${theme}/${sizeName}]`, [...new Set(problems)].join('\n  '));
    await context.close();
  }
}
await browser.close();
console.log(`saved screenshots to ${out}/`);
