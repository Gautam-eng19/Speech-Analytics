// Browser smoke test: drives the built dashboard in a real Chromium the way a user would.
//
//   BASE_URL=http://127.0.0.1:8000 node scripts/smoke.mjs
//
// Needs a running server that serves the built dashboard (see scripts/screenshots.mjs). The API itself is mocked inside the browser for
// the upload and recording flows, so no baseline or speech model is needed; the demo samples provide the data. Exits 1 on any failure.
import { chromium } from 'playwright-core';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const base = process.env.BASE_URL ?? 'http://127.0.0.1:8000';
const samples = fileURLToPath(new URL('../public/samples/', import.meta.url));

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

const results = [];
const check = (name, ok, detail = '') => {
  results.push(ok);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`);
};

const index = await (await fetch(`${base}/samples/index.json`)).json();
const idOf = (sampleId) => index.samples.find((s) => s.id === sampleId).analysis_id;
const sampleResult = JSON.parse(readFileSync(join(samples, 'rushed-explanation.json'), 'utf8'));
const catalog = {
  baselines: [{
    baseline_id: 'demo_talk', dataset_version: 'demo', n_baseline_recordings: 5, n_pauses_within_phrase: 40, n_rate_windows: 20, passage_id: 'demo_talk',
    passage_text: 'Good morning, everyone, and thank you for joining us today.', passage_title: 'Project talk (demo passage)', passage_word_count: 123,
    sha256: 'a'.repeat(64), thin_pause_statistics: false, thin_rate_statistics: false,
  }],
  unavailable: [],
};

const browser = await chromium.launch({
  executablePath: findChrome(),
  args: ['--no-sandbox', '--autoplay-policy=no-user-gesture-required', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
});

async function session(fn, options = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['microphone'], ...options });
  const page = await context.newPage();
  const problems = [];
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error' && !/status of 4\d\d/.test(m.text())) problems.push(`console: ${m.text()}`); });
  await fn(page);
  check('no script errors', problems.length === 0, problems.join('; '));
  await context.close();
}

// ---- 1. the timeline: zoom, pan, select, keyboard, palette, playback ---------------------------------------------------------
console.log('\n# timeline and shortcuts');
await session(async (page) => {
  await page.goto(`${base}/#/a/${idOf('mixed-flaws')}/timeline`, { waitUntil: 'networkidle' });
  await page.waitForSelector('.stack__plots');
  const windowText = async () => (await page.locator('.scope__window').innerText()).replace(/\s+/g, ' ');
  const box = await page.locator('.stack__plots').boundingBox();
  const at = (fraction) => box.x + box.width * fraction;
  const y = box.y + 200;

  const start = await windowText();
  check('starts fully zoomed out', /×1\.0/.test(start), start);
  await page.mouse.move(at(0.5), y);
  await page.mouse.wheel(0, -600);
  await page.waitForTimeout(150);
  const zoomed = await windowText();
  check('wheel zooms in around the pointer', !/×1\.0/.test(zoomed), zoomed);
  await page.mouse.down();
  await page.mouse.move(at(0.3), y, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(100);
  check('dragging pans', (await windowText()).split(' ')[0] !== zoomed.split(' ')[0], await windowText());
  await page.mouse.dblclick(at(0.5), y);
  check('double-click fits the whole recording', /×1\.0/.test(await windowText()));
  await page.keyboard.press('+');
  check('+ zooms in', !/×1\.0/.test(await windowText()));
  await page.keyboard.press('0');
  check('0 fits', /×1\.0/.test(await windowText()));

  await page.locator('.flawband').first().click();
  check('choosing a finding fills the inspector with its evidence', /Participant rate|Pause length|Participant level/.test((await page.locator('.side-block--selected').innerText().catch(() => ''))));
  await page.keyboard.press('Escape');
  check('Escape clears the selection', (await page.locator('.side-block--selected').count()) === 0);

  await page.mouse.move(at(0.2), box.y + 150);
  check('hovering reads values from the result', /Loudness/.test(await page.locator('.readings').first().innerText()));
  check('a crosshair follows the pointer', (await page.locator('.ov--cross').count()) === 1);

  await page.locator('.transport__play').click();
  await page.waitForTimeout(2000);
  const seconds = parseFloat((await page.locator('.transport__time').innerText()).split('/')[0].trim().split(':')[1]);
  check('playback runs in real time', seconds > 0.8, `${seconds} s after 2 s`);
  await page.locator('.transport__play').click();

  await page.keyboard.press('Control+k');
  await page.waitForSelector('.palette');
  await page.keyboard.type('library');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(250);
  check('the command palette navigates', page.url().endsWith('#/library'), page.url());
  await page.keyboard.press('g');
  await page.keyboard.press('s');
  check('g s goes to settings', page.url().endsWith('#/settings'));
  const theme = await page.evaluate(() => document.documentElement.dataset.theme);
  await page.keyboard.press('t');
  check('t switches the theme', (await page.evaluate(() => document.documentElement.dataset.theme)) !== theme);
});

// ---- 1b. the landing page: headline, instrument, calls to action, navigation ---------------------------------------------------
console.log('\n# landing page');
await session(async (page) => {
  await page.goto(`${base}/#/`, { waitUntil: 'networkidle' });
  await page.waitForSelector('button.hx-flag');
  await page.waitForTimeout(1800);
  check('one headline', (await page.locator('h1').count()) === 1 && /Hear the difference/.test(await page.locator('h1').innerText()));
  check('there is no sign-in on the page', (await page.getByText(/sign[ -]?in|log[ -]?in/i).count()) === 0);
  const nav = page.locator('.lnav');
  const names = await nav.getByRole('link').allInnerTexts();
  check('the navigation links to the sections and the existing pages', ['Method', 'Evidence', 'Journey', 'Library', 'Custom passage', 'Help'].every((n) => names.includes(n)), names.join(', '));
  const flags = await page.locator('button.hx-flag').count();
  check('every finding of the demo sample is on the instrument', flags === 3, `${flags} findings`);

  const box = await page.locator('.hx').boundingBox();
  await page.mouse.move(box.x + box.width * 0.14, box.y + 200, { steps: 5 });
  await page.waitForTimeout(250);
  const reading = await page.locator('.hx__read').innerText();
  check('hovering reads the measurement at that moment from the result', /words\/min/.test(reading) && /dBFS/.test(reading) && /Too fast/.test(reading), reading.replace(/\s+/g, ' '));
  check('the pointer lights the instrument and shifts only the background', (await page.locator('.hx').getAttribute('data-active')) === 'true');
  const flagBefore = await page.locator('button.hx-flag').first().boundingBox();
  await page.mouse.move(box.x + box.width * 0.6, box.y + 120, { steps: 5 });
  await page.waitForTimeout(900);
  const flagAfter = await page.locator('button.hx-flag').first().boundingBox();
  check('text and buttons do not move with the pointer', Math.abs(flagBefore.x - flagAfter.x) < 0.5 && Math.abs(flagBefore.y - flagAfter.y) < 0.5);
  await page.mouse.move(box.x - 30, box.y - 30, { steps: 3 });
  await page.waitForTimeout(300);
  check('moving away returns the readout to rest', /–/.test(await page.locator('.hx__read-row dd').first().innerText()));

  await page.locator('button.hx-flag').first().click();
  await page.waitForTimeout(1500);
  const playing = await page.evaluate(() => ({ t: document.querySelector('audio').currentTime, paused: document.querySelector('audio').paused, live: document.querySelectorAll('.is-live').length }));
  check('a finding plays its own moment and is marked while it plays', !playing.paused && playing.t > 5.3 && playing.live >= 1, JSON.stringify(playing));
  await page.locator('.hx-play').click();
  check('the play button pauses it', await page.evaluate(() => document.querySelector('audio').paused));

  await page.locator('.lhero__cta').getByRole('button', { name: /Analyse a recording/ }).click();
  await page.waitForTimeout(900);
  check('the first call to action goes to the analysis flow and focuses it', await page.evaluate(() => document.activeElement?.id === 'start-title' && location.hash === '#/'));
  await page.locator('#main').evaluate((el) => el.scrollTo({ top: 0 }));
  await page.getByRole('button', { name: 'Explore a demo analysis' }).click();
  await page.waitForURL(/#\/a\/.*\/timeline/, { timeout: 5000 }).catch(() => undefined);
  check('the second call to action opens the demo analysis', /#\/a\/.*\/timeline/.test(page.url()), page.url());
});

// ---- 2. upload with a mocked API ---------------------------------------------------------------------------------------------
console.log('\n# upload (mocked API)');
await session(async (page) => {
  let mode = 'error';
  await page.route('**/api/v1/baselines', (r) => r.fulfill({ json: catalog }));
  await page.route('**/api/v1/analyze', async (r) => {
    await new Promise((resolve) => setTimeout(resolve, 600));
    return mode === 'ok' ? r.fulfill({ json: sampleResult }) : r.fulfill({ status: 400, json: { error: 'AUDIO_TOO_LONG', detail: 'audio of 400.0 s exceeds limit of 300.0 s' } });
  });
  await page.goto(`${base}/#/`, { waitUntil: 'networkidle' });
  check('the baseline list comes from the catalogue', (await page.locator('#baseline option').count()) === 1);
  await page.setInputFiles('input[type=file]', join(samples, 'rushed-explanation.wav'));
  await page.waitForSelector('.drop__file-name');
  await page.getByRole('button', { name: 'Analyse recording' }).click();
  await page.waitForSelector('.progress');
  check('progress is shown while the server works', true);
  await page.waitForSelector('.error-card');
  check('an API error is shown with its own detail', /300\.0 s/.test(await page.locator('.error-card').innerText()));
  await page.getByRole('button', { name: 'Dismiss' }).click();
  mode = 'ok';
  await page.getByRole('button', { name: 'Analyse recording' }).click();
  await page.waitForURL(/#\/a\/.*\/overview/);
  await page.waitForSelector('.score__num');
  check('the result opens with the backend score', (await page.locator('.score__num').innerText()).trim() === sampleResult.scores.composite_score.toFixed(1));
  check('the uploaded audio plays in the dashboard', (await page.locator('.transport').count()) === 1);
});

// ---- 3. recording with a fake microphone ----------------------------------------------------------------------------------------
console.log('\n# recording (fake microphone)');
await session(async (page) => {
  let uploaded = null;
  await page.route('**/api/v1/baselines', (r) => r.fulfill({ json: catalog }));
  await page.route('**/api/v1/analyze', async (r) => { uploaded = r.request().postDataBuffer(); return r.fulfill({ json: sampleResult }); });
  await page.goto(`${base}/#/`, { waitUntil: 'networkidle' });
  await page.getByRole('radio', { name: 'Record now' }).click();
  check('the passage is the prompt', (await page.locator('.rec__prompt-text').innerText()).startsWith('Good morning'));
  await page.getByRole('button', { name: 'Start recording' }).click();
  await page.waitForSelector('.rec__live');
  await page.waitForTimeout(2200);
  const shown = parseFloat((await page.locator('.rec__time').innerText()).split(':')[1]);
  check('the clock follows the captured samples', shown > 1.4 && shown < 3.4, `${shown} s`);
  check('the level meter moves', Number(await page.getByRole('meter', { name: 'Input level' }).getAttribute('aria-valuenow')) > -60);
  await page.getByRole('button', { name: 'Stop' }).click();
  await page.waitForSelector('.rec__take');
  check('the take is offered as a 16 kHz mono WAV', /16 kHz mono WAV/.test(await page.locator('.rec__take-meta').innerText()));
  await page.getByRole('button', { name: 'Use this recording' }).click();
  await page.getByRole('button', { name: 'Analyse recording' }).click();
  await page.waitForURL(/#\/a\/.*\/overview/);
  const body = uploaded;
  const wav = body.subarray(body.toString('latin1').indexOf('RIFF'));
  const rate = wav.readUInt32LE(24), channels = wav.readUInt16LE(22), bits = wav.readUInt16LE(34), dataBytes = wav.readUInt32LE(40);
  check('the uploaded file is 16 kHz, mono, 16-bit', rate === 16000 && channels === 1 && bits === 16, `${rate} Hz, ${channels} ch, ${bits} bit`);
  check('its length matches the recording', Math.abs(dataBytes / 2 / rate - shown) < 1.2, `${(dataBytes / 2 / rate).toFixed(2)} s`);
  let energy = 0;
  for (let i = 0; i < dataBytes / 2; i++) { const v = wav.readInt16LE(44 + i * 2) / 32768; energy += v * v; }
  check('it contains the signal that was captured', Math.sqrt(energy / (dataBytes / 2)) > 0.001);
});

await browser.close();
const failed = results.filter((ok) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
