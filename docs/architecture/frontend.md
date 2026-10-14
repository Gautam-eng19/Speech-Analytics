# Dashboard (frontend)

The dashboard presents the analysis: it shows a participant's delivery against the baseline, where it deviated, the
measured evidence, why that is a flaw, and what to try. This page describes how it is built and where each number on screen comes from.

## 1. The boundary

The dashboard **renders the backend's `AnalysisResult` and computes no analytics**. It may:

- look values up: the frame nearest a time, the pause that contains a time, the word being spoken (`src/lib/lookup.ts`);
- order, filter and group lists, format numbers with fixed decimals, choose axis ranges;
- thin a long series for drawing (the minimum and maximum of each pixel column are kept, so peaks never disappear);
- draw two pieces of geometry derived from backend numbers, both labelled on screen: the baseline bands (mean ± 1 and 2 standard
  deviations) and the dashed "where the rule flags" line on the evidence gauge (mean + the finding's own `rule.threshold_z` × std).

Scores, severities, reliabilities, z-scores, rates, pause lengths and deviations are only read, never derived. Page tests compare the
numbers on screen with the numbers in the result.

### Where each number comes from

| On screen | Field of `AnalysisResult` |
|---|---|
| Deviation score (large numeral) | `scores.composite_score` |
| Score by dimension: score, weight, findings, penalty | `scores.feature_scores.<dimension>` (`score`, `weight`, `flaw_count`, `penalty_total`) |
| "Not scored" rows and their reason | absence from `feature_scores` + the matching note (`<dimension>_not_scored`) |
| Readout paragraph | `overall_summary` (split into sentences, text untouched) |
| Finding: type, interval, severity, reliability | `flaws[].type`, `start_s`, `end_s`, `severity`, `reliability` |
| Evidence rows and the gauge | `flaws[].evidence` (rate, energy or pause evidence), `flaws[].rule` |
| Explanation, recommendation, warnings, affected words | `flaws[].explanation`, `recommendation`, `warnings`, `affected_words` |
| Loudness lane | `features.energy_timeline` |
| Pitch lane | `features.f0_timeline` (voiced frames only) |
| Speech-rate lane | `features.speech_rate_timeline` (one value per rolling window, drawn at its midpoint) |
| Pause lane, pause table, gaps in the transcript | `features.pause_events` |
| Words lane, transcript | `alignment` |
| Baseline bands, baseline statistics page | `baseline_stats` |
| Notes and limitations | `notes[]` (every note is shown) |
| Provenance | `analysis_id`, `audio.sha256`, `baseline.sha256`, `config_version`, `config_fingerprint`, `pipeline_version`, `scores.scoring_version`, `processing_meta` |
| Time of everything | source time: the timeline of the uploaded file (`audio.trim_start_s`; `audio.source_duration_s`) |

## 2. Running it

```bash
cd frontend
npm ci
npm run dev            # Vite on :5173, proxies /api to the backend on :8000
npm run build          # typecheck + production build into frontend/dist
npm test               # Vitest (jsdom)
npm run typecheck
npm run gen:types      # regenerate src/api/schema.d.ts from openapi.json
npm run shots          # screenshots of every page (needs a running server and a Chromium)
npm run a11y           # axe-core audit of every page and state, light and dark (same needs)
npm run smoke          # drives the running app in Chromium: timeline, shortcuts, upload, recording with a fake microphone
npm run samples        # rebuild the demo samples (needs ffmpeg with libflite)
```

Production: build once, then `python -m uvicorn app.main:app --app-dir backend` serves the dashboard at `/` and the API at `/api/v1`
on one origin. `FRONTEND_DIST_DIR` and `CORS_ORIGINS` are described in `.env.example`.

After a backend change that alters the API schema: `python scripts/export_openapi.py` (updates `frontend/openapi.json`), then
`npm run gen:types`. A backend test fails when the snapshot is stale; `python scripts/export_openapi.py --check` is the same check.

## 3. Structure

```
frontend/
  public/samples/        demo recordings, their results and index.json
  scripts/screenshots.mjs  visual QA: every page, light and dark, desktop / tall / phone
  scripts/a11y.mjs         axe-core audit of every page and interactive state, both themes
  scripts/smoke.mjs        end-to-end checks in a real Chromium (42 of them), incl. the landing page and a take from the fake microphone
  src/
    api/                 client.ts (fetch + upload with progress), types.ts (names for generated types), schema.d.ts (generated)
    app/                 App (routes), Shell, Sidebar, Topbar, Ribbon, Transport, CommandPalette, GlobalKeys, router
    charts/              TimelineStack (shared plot), lanes.tsx, overlays.tsx, geometry.ts, useWidth.ts, ScoreRadar.tsx (the score profile on the Overview page), useTweened.ts
    components/          Icon (custom set), ui.tsx (buttons, chips, meters, dialog, toasts), page.tsx, EvidenceView.tsx
    features/            one folder per page: analyze, library, overview, timeline, flaws, signals, transcript, baseline, report, settings, help;
                         landing/ is the home page (the instrument, its geometry, the sections, the landing navigation), shown by the analyze route
    lib/                 pure helpers: format, time, decimate, result, lookup, evidence, flawMeta, notesMeta, settings, store, csv, useMotion
    recording/           recorder (microphone to samples), resample (to 16 kHz), wav (16-bit PCM file)
    state/               stores: analysis, player, history, connection, ui, actions
    styles/              tokens, base, components, shell, pages, timeline, landing (plain CSS, custom properties)
  tests/                 Vitest suites (see section 8)
```

### Routes

`#/` the landing page, which contains the new-analysis flow · `#/library` · `#/custom` · `#/settings` · `#/help` · `#/a/<analysis id>/<view>[/<finding id>]` with `view` one of
`overview`, `timeline`, `flaws`, `signals`, `transcript`, `baseline`, `report`. A demo sample is opened by its analysis id like any
other analysis; an id the samples do not know is fetched from the API.

### State

Small external stores (`src/lib/store.ts`, `useSyncExternalStore`): the open analysis and how it was loaded, the audio element and the
playhead (a separate store, updated every animation frame while playing, so only the overlays re-render), the shared time window and
selection, hover time, settings and history (localStorage), connection health and the baseline catalogue. A request that has been
replaced by a newer one can no longer change the state (`superseded` in `state/analysis.ts`).

Settings (`sa.settings.v1`): theme (dark unless the user chose otherwise), density, motion, time format, sidebar, API address, timeline lanes, follow-playhead, ground truth.
History (`sa.history.v1`): id, title, score, counts of the last 40 opened analyses. Audio and results are never stored in the browser.

## 4. Design system

Identity: **VAANI, a precision acoustic instrument.** Obsidian and graphite surfaces, hairline rules, ivory type, and two colours that carry meaning
and nothing else: **cyan is signal** (the delivery, live audio, anything interactive) and **copper is deviation** (only where the pipeline reported one); steel is the quiet voice
(the reference, secondary text). Dark is the primary theme; the light theme is the same system on ivory. Large serif titles, monospace for every measurement and
technical label, thin dividers and open layouts instead of a card around everything, two very faint pools of light and a fine grain on the large dark fields.

- **Tokens** (`styles/tokens.css`): palette primitives, colour roles, type scale (`--fs-title` for page titles, `--fs-display` for the landing headline), spacing (4 px grid), radii, motion,
  layout sizes, texture; both themes are defined there and nowhere else. `html[data-theme]`, `data-density` and `data-motion` select them; `.paper` re-applies the light values
  (the printable report is paper in either theme).
- **Type**: IBM Plex Sans (interface), IBM Plex Mono (numbers, timestamps, labels), Newsreader (titles, the score numeral, passage and transcript text); all self-hosted, SIL OFL 1.1.
- **Finding colours**: eight hues, each also a glyph (`g-fast`, `g-slow`, `g-pause`, ...) and a name, so colour is never the only signal. Copper (`--dev`) is the generic deviation colour for places that
  do not need the type (severity bars, the landing instrument, the radar). Finding text is mixed toward the ink so it reads on its own tint.
- **Contrast**: `tests/tokens.test.ts` asserts WCAG 2.1 AA for the pairs the stylesheets use, in both themes; axe covers the rest (section 8).
- **Icons and mark**: one custom icon set on a 24-unit grid with one stroke weight (`components/Icon.tsx`); the VAANI mark is two strokes that leave one point together, the delivery drifting away and ending in the copper marker.
- **Motion**: transforms and opacity, one calm entrance per page, nothing that loops without meaning. Decorative motion (the drifting grid, the travelling marker) pauses when it is off screen and
  is off when reduced motion is asked for (system setting or Settings); then every picture is complete at once. Pointer response lives on the landing instrument only (section 6) and is off for coarse pointers.
- **Reusable pieces**: `PageHead` (eyebrow, title, meta, actions), `Panel`, `Figure`, `Fact`, `Chip`, `FlawTag`, `Meter`, `Segmented`, `Button` (sm, md, lg), `Tip`, `Kbd`,
  `ScoreRadar` with its legend, `TimelineStack` and its overlays, the landing's `SectionHead`.

## 5. The plot system (`src/charts/`)

`TimelineStack` is the one plot used by the overview figure, the timeline, the signal charts and the close-up of a finding. It is a
label column plus a plot column; every lane draws on the same x scale (the shared time window).

| Lane | Source | Drawing |
|---|---|---|
| Findings | `flaws` | one button per finding (type colour + glyph); selected one outlined |
| Injected (samples) | `index.json` ground truth | solid = detected, dashed = missed |
| Words | `alignment` | word boxes (text when wide enough, ticks otherwise), fainter = lower confidence |
| Loudness | `energy_timeline` | peak envelope per pixel column on a fixed -80..0 dBFS scale; baseline bands |
| Pitch | `f0_timeline` | dots and short contours where voiced; baseline 5-95 % range and mean |
| Speech rate | `speech_rate_timeline` | line with a dot per window; baseline bands |
| Pauses | `pause_events` | bars (taller = longer; darker = between sentences); flagged ones in the finding's colour |

Interaction (timeline): wheel zooms around the pointer, Shift + wheel or drag pans, double-click fits, `+` `-` `0` zoom and fit, click moves
the playhead, the crosshair and the readout follow the pointer, "Follow" pages the view along during playback. The delivery ribbon above
every analysis page shows the whole recording, its findings and the visible window, and can be dragged.

Overlays (playhead, crosshair, finding columns, selection, trimmed silence, active word, the part already played, the finding being played) subscribe to their stores themselves, so zooming
or hovering does not redraw the lanes more than once per change. While the audio runs, the played part is washed (in the plots and in the ribbon) and the finding being played breathes;
traces are drawn in from the left when a plot first appears (once; not in print).

## 6. Pages

- **Landing page** (the home route, `features/landing/`): a hero with the headline and two calls to action (analyse a recording: scroll to the flow and focus it; explore a demo analysis: open it on the timeline),
  the **instrument** under it, then method, evidence and journey sections, the analysis flow, a footer. The instrument draws the demo sample `mixed-flaws`, a synthetic voice analysed by the real pipeline: the speech-rate trace over the reference corridor,
  the loudness envelope, a labelled interval per finding with the backend's evidence line. Geometry is `heroModel.ts` (pure, tested). Hovering reads the measurement at that moment from the result (`lib/lookup.ts`); clicking plays that moment;
  a finding's label plays its interval; the pointer lights the bars under it and shifts only the atmosphere behind the data. Without the sample it is a drawing labelled "Illustration". The landing navigation replaces the top bar on this route (no sign-in: the product has no accounts),
  and the sidebar is the drawer at every width.
- **New analysis (the flow inside the landing)**: upload (drag and drop, WAV or MP3, preview) or record in the browser (section 6a), baseline and passage from `GET /api/v1/baselines` (with thin-statistics
  warnings and the passage to read), optional manual transcript, honest progress (upload bytes, then "analysing" with elapsed time and a
  cancel; the API reports nothing finer), API errors with their own detail, demo samples, recent analyses.
- **Overview**: score instrument, readout, figure of the whole recording, findings strongest first, the score profile (the radar: the reference ring, this recording, copper where findings cost points, legend, tooltip, grows into its values), notes, provenance.
- **Timeline**: the scope, with an inspector (values at the cursor, selected finding, legend).
- **Flaws**: list with filter and sort; for one finding: close-up, evidence gauge and table, explanation, recommendation, rule, warnings,
  affected words; `j` `k` move, Enter plays; "Export CSV" downloads every finding as a table (section 6b).
- **Signals**: linked charts for rate, loudness, pitch and pauses with the baseline numbers, a table of every value for the small series,
  the pause table and the MFCC summary.
- **Transcript**: words with timing; underlines mark findings; the space after a word is stretched by the pause that follows it; click to seek.
- **Baseline and method**: baseline statistics and identity, the passage, the pipeline, the finding vocabulary and its status, honest scope.
- **Report**: an A4 printable document (print stylesheet; "Save as PDF" in the print dialog).
- **Library, Settings, Help**: samples and local history, appearance and connection, glossary and shortcuts.

### 6a. Recording (`src/recording/`, `features/analyze/RecorderPanel.tsx`)

"Record now" shows the passage to read (from the chosen baseline), asks for the microphone only when **Start** is pressed, and shows a
scope of the recent input level on a dB scale, the elapsed time, and the chosen microphone. The level and the clipping warning (a peak at
or above 0.99) are capture aids for placing the microphone; nothing is measured about the delivery in the browser.

- The browser's echo cancellation, noise suppression and automatic gain control are requested **off**; if the browser reports that it kept any
  on, the panel warns before the take is used.
- Samples are collected raw by an AudioWorklet (ScriptProcessor where worklets are missing), converted from the native rate to 16 kHz mono by
  `resample.ts` (windowed sinc; the same samples always give the same bytes) and written as a 16-bit WAV by `wav.ts`. A five-minute take is
  9.6 MB, inside the API's default 10 MiB upload limit.
- The longest take is 300 s (the API default `MAX_DURATION_S`); the panel stops and says so. Unsupported browsers, insecure pages (not https or
  localhost), a blocked permission, a missing or busy microphone each have their own message. Leaving the page releases the microphone.
- "Use this recording" puts the file into the upload form, from where it is analysed like any chosen file. Discard throws it away; nothing is
  stored in the browser.

### 6b. Export and sharing

`Export CSV` (Flaws page, command palette) writes `<recording name>.<first 8 characters of the analysis id>.findings.csv`: one row per finding in
time order, backend values unrounded, evidence flattened to `evidence.<field>` columns, RFC 4180 quoting, CRLF, UTF-8 with a byte-order mark
for spreadsheets. An analysis without findings says so instead of saving an empty table. (The full result as JSON remains available from the
same palette.) "Copy a link to this page"
(top bar, command palette) copies the current address; it opens the same analysis for anyone who reaches the same server while it still
holds the result.

## 7. Honesty rules

Synthetic samples are labelled wherever they appear. A dimension that was not scored is a row that says why. Every backend note is shown. A finding keeps
its rule, warnings and low-confidence flag. The score is described as a deviation from the baseline, not as a grade. A result opened by id has no audio
and says so. Rate findings are window-resolution, pitch is context only, and thresholds are uncalibrated: all three are stated in the interface.

## 8. Tests and visual QA

`npm test` runs 386 tests: the landing page and its geometry, the radar and its animation, formatting, time windows, decimation, routing, settings, stores, the API client (with `fetch` and
`XMLHttpRequest` stand-ins), lookups, evidence formatting, the plot interactions (wheel, drag, click, select), every page with real result
fixtures (the shipped samples), the store (including overlapping requests), the application (routing, keyboard, palette), the colour tokens,
the recorder (against a scripted audio graph: permission and device errors, voice-processing flags, limit, cancel, byte-exact WAV), the
converter (tone level, anti-aliasing, determinism), the recorder panel and the CSV export (parsed back with an RFC 4180 reader).
The suite was checked with injected bugs (27 mutations of the helpers, plots, store and pages, and 23 of the recorder, converter, WAV
writer and CSV writer); every one made a test fail. One recorder mutation first survived (the length of the converted take when the last
output sample is incomplete); a test now covers it.

`npm run a11y` runs axe-core (WCAG 2.1 A and AA) on every page and on the interactive states (command palette, shortcuts dialog, selected finding, zoomed timeline, collapsed sidebar, phone navigation drawer, phone layouts, and six landing states: settled, pointer on the instrument, a finding playing, drawer open, phone) in both themes; on 2026-10-14 all 70 combinations pass (the recorder states included). The audit once found and the fixes removed: small text in the decorative grey, a white-on-orange playhead label, an unlabeled file input, scroll regions without keyboard access, unnamed icon links in the collapsed sidebar, low-confidence words that were faded below readable contrast (they are now tinted instead), and, with the landing page, the interval text of a highlighted label on the instrument. A closed navigation drawer is hidden, not only moved off screen, so its links are not in the tab order.

`npm run shots` writes PNGs of every page in light and dark at desktop, tall and phone sizes for review. Interaction was also driven in a real
Chromium (zoom, pan, selection, shortcuts, palette, theme, playback, upload with a mocked API, the landing instrument); `npm run smoke` repeats those checks (42
of them) and also records a take from Chromium's fake microphone and inspects the uploaded WAV header. A layout audit (every page at eight widths from 320 to 2560 px, both themes) found no horizontal overflow
after two fixes (a table in the report on the narrowest screen, hit areas of the radar's labels).

## 9. Not done yet

A waveform (needs decoding audio in the browser; the loudness timeline serves for now), a comparison of two analyses
(would subtract backend numbers in the browser; better done by the backend), canvas drawing for very long recordings, and any run against
the real Whisper/WhisperX models or a real recording. The recorder has only been exercised with Chromium's fake microphone and with test
doubles: a real microphone, Safari, Firefox and phones are untested.
