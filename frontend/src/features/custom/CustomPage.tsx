import { useEffect, useMemo, useRef, useState } from 'react';
import { isSupportedAudioName } from '@/api/client';
import type { BaselineSummary, CustomBaselineResult } from '@/api/types';
import { Icon } from '@/components/Icon';
import { PageHead } from '@/components/page';
import { Button, Chip, Dialog, Panel, Segmented } from '@/components/ui';
import { fmtBytes, fmtNum, plural } from '@/lib/format';
import { analysisPath, navigate } from '@/app/router';
import { analysisStore, analyzeFile, dismissError, useAnalysis } from '@/state/analysis';
import { refreshCatalog, useCatalog, useConnection } from '@/state/connection';
import { cancelCustom, createCustomBaseline, deleteCustomBaseline, resetCustom, useCustom } from '@/state/custom';
import { Progress } from '../analyze/AnalyzePage';
import { FileDrop } from '../analyze/FileDrop';
import { PreviewPlayer } from '../analyze/PreviewPlayer';
import { RecorderPanel } from '../analyze/RecorderPanel';

/**
 * Limits shown to the user while typing. They mirror the server's settings (CUSTOM_MIN_PASSAGE_WORDS and the others) only to give early
 * feedback; the server checks everything again and its message is what is shown when it refuses. Nothing here is analysis.
 */
export const LIMITS = { minWords: 30, maxWords: 400, minTakes: 2, goodTakes: 3, maxTakes: 6 } as const;

/** Words and sentences of the typed passage, for the early hints under the text box. */
export function describePassage(text: string): { words: number; sentences: number } {
  const trimmed = text.trim();
  if (!trimmed) return { words: 0, sentences: 0 };
  return { words: trimmed.split(/\s+/).length, sentences: (trimmed.match(/[.!?]+["')\]]*(?=\s|$)/g) ?? []).length };
}

/** What is still missing before the baseline can be made, in words; null when nothing is. */
export function passageProblem(text: string): string | null {
  const { words, sentences } = describePassage(text);
  if (words === 0) return 'Type or paste the passage you will read.';
  if (words < LIMITS.minWords) return `${plural(LIMITS.minWords - words, 'more word')} needed (at least ${LIMITS.minWords}).`;
  if (words > LIMITS.maxWords) return `${plural(words - LIMITS.maxWords, 'word')} too many (at most ${LIMITS.maxWords}).`;
  if (sentences < 2) return 'The passage needs at least two sentences, each ending in . ! or ?';
  return null;
}

function BaselineProgress() {
  const state = useCustom();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, []);
  const p = state.progress;
  if (!p) return null;
  const uploading = p.phase === 'uploading';
  const share = p.total > 0 ? p.loaded / p.total : 0;
  return (
    <div className="progress" role="status" aria-live="polite">
      <div className="progress__head">
        <span className="progress__phase">{uploading ? 'Uploading the recordings' : 'Making the baseline on the server'}</span>
        <span className="num progress__time">{fmtNum(Math.max(0, (now - p.startedAt) / 1000), 0)} s</span>
      </div>
      <div className={`progress__bar ${uploading ? '' : 'is-indeterminate'}`} aria-hidden="true"><i style={uploading ? { width: `${share * 100}%` } : undefined} /></div>
      <p className="progress__text">
        {uploading
          ? `${fmtBytes(p.loaded)} of ${fmtBytes(p.total)} sent.`
          : 'Each recording is aligned to your passage word by word and measured. This takes roughly a minute per recording the first time.'}
      </p>
      <Button size="sm" variant="ghost" icon="x" onClick={cancelCustom}>Cancel</Button>
    </div>
  );
}

function ResultCard({ result }: { result: CustomBaselineResult }) {
  const takes = result.takes ?? [];
  const warnings = result.warnings ?? [];
  return (
    <div className="custom-result" role="group" aria-label="The baseline that was made">
      <div className="custom-result__chips">
        <Chip tone="good" icon="check">Baseline ready</Chip>
        {result.already_existed ? <Chip tone="info" icon="info">Already existed, nothing recomputed</Chip> : null}
        {result.word_profile_built
          ? <Chip tone="good" icon="target">Word-by-word comparison</Chip>
          : <Chip tone="warn" icon="alert-triangle">Overall averages only</Chip>}
        {result.pitch_profile_built ? <Chip tone="good" icon="chart">Flat pitch is checked</Chip> : <Chip tone="neutral">Flat pitch not checked</Chip>}
      </div>
      {takes.length > 0 ? (
        <table className="table custom-result__table">
          <thead><tr><th>Recording</th><th className="r">Length</th><th className="r">Pace</th><th className="r">Words found</th><th className="r">Matches the text</th></tr></thead>
          <tbody>
            {takes.map((t) => (
              <tr key={t.filename}>
                <td className="truncate" title={t.filename}>{t.filename}</td>
                <td className="num r">{fmtNum(t.duration_s, 1)} s</td>
                <td className="num r">{fmtNum(t.words_per_min, 0)} wpm</td>
                <td className="num r">{fmtNum(t.timed_word_share * 100, 0)}%</td>
                <td className="num r">{t.content_match === null || t.content_match === undefined ? '—' : `${fmtNum(t.content_match * 100, 0)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {warnings.length > 0 ? (
        <ul className="custom-warnings">
          {warnings.map((w) => <li key={w}><Icon name="alert-triangle" size={15} /> <span>{w}</span></li>)}
        </ul>
      ) : null}
      <p className="field__hint">Only the measured statistics and your passage text are stored on the server; the recordings are not kept.</p>
    </div>
  );
}

function CustomList({ items, activeId, onUse, onDelete }: { items: BaselineSummary[]; activeId: string; onUse: (id: string) => void; onDelete: (item: BaselineSummary) => void }) {
  if (items.length === 0) return <p className="muted">Nothing yet. Passages you add are listed here and can also be chosen on the New analysis page.</p>;
  return (
    <ul className="custom-list">
      {items.map((b) => (
        <li key={b.baseline_id} className={`custom-list__item ${b.baseline_id === activeId ? 'is-active' : ''}`}>
          <div className="custom-list__text">
            <span className="custom-list__title truncate" title={b.passage_title ?? b.baseline_id}>{b.passage_title ?? b.baseline_id}</span>
            <span className="muted custom-list__meta">{plural(b.passage_word_count ?? 0, 'word')} · {plural(b.n_baseline_recordings, 'recording')}</span>
          </div>
          <Button size="sm" variant={b.baseline_id === activeId ? 'primary' : 'secondary'} onClick={() => onUse(b.baseline_id)} aria-pressed={b.baseline_id === activeId}>
            {b.baseline_id === activeId ? 'In use' : 'Use'}
          </Button>
          <Button size="sm" variant="ghost" icon="trash" aria-label={`Delete ${b.passage_title ?? b.baseline_id}`} onClick={() => onDelete(b)} />
        </li>
      ))}
    </ul>
  );
}

export function CustomPage() {
  const custom = useCustom();
  const analysis = useAnalysis();
  const catalog = useCatalog();
  const connection = useConnection();
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [takes, setTakes] = useState<File[]>([]);
  const [source, setSource] = useState<'file' | 'record'>('file');
  const [problem, setProblem] = useState<string | null>(null);
  const [reading, setReading] = useState<File | null>(null);
  const [readingSource, setReadingSource] = useState<'file' | 'record'>('file');
  const [readingProblem, setReadingProblem] = useState<string | null>(null);
  const [activeId, setActiveId] = useState('');
  const [toDelete, setToDelete] = useState<BaselineSummary | null>(null);
  const picker = useRef<HTMLInputElement>(null);
  const stepThree = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (catalog.status === 'idle' || catalog.status === 'error') void refreshCatalog();
    // Load once on arrival; the list is refreshed after every change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const customBaselines = useMemo(() => (catalog.data?.baselines ?? []).filter((b) => b.custom), [catalog.data]);
  const active = customBaselines.find((b) => b.baseline_id === activeId) ?? null;

  // A baseline that was just made becomes the one the reading is compared with.
  useEffect(() => {
    if (custom.result) setActiveId(custom.result.baseline_id);
  }, [custom.result]);
  useEffect(() => {
    if (!active && customBaselines.length > 0 && !customBaselines.some((b) => b.baseline_id === activeId)) setActiveId(customBaselines[0]!.baseline_id);
    if (customBaselines.length === 0 && catalog.status === 'ready') setActiveId('');
  }, [customBaselines, active, activeId, catalog.status]);

  const offline = connection.status === 'offline';
  const busyBaseline = custom.status === 'working';
  const busyAnalysis = analysis.status === 'loading';
  const passageIssue = passageProblem(text);
  const stats = describePassage(text);
  const canMake = !passageIssue && takes.length >= LIMITS.minTakes && takes.length <= LIMITS.maxTakes && !busyBaseline && !offline;

  const addTakes = (files: File[]) => {
    const accepted: File[] = [];
    const rejected: string[] = [];
    for (const f of files) {
      if (!isSupportedAudioName(f.name)) rejected.push(`“${f.name}” is not a WAV or MP3 file.`);
      else accepted.push(f);
    }
    const room = LIMITS.maxTakes - takes.length;
    if (accepted.length > room) rejected.push(`At most ${LIMITS.maxTakes} recordings can be used; ${plural(accepted.length - room, 'file')} left out.`);
    setProblem(rejected.length ? rejected.join(' ') : null);
    if (accepted.length) setTakes((previous) => [...previous, ...accepted.slice(0, room)]);
    if (accepted.length) resetCustom();
  };

  const make = async () => {
    const ok = await createCustomBaseline({ passageText: text, title, files: takes });
    if (ok) window.setTimeout(() => stepThree.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }), 50);
  };

  const acceptReading = (candidate: File | undefined) => {
    if (!candidate) return;
    if (!isSupportedAudioName(candidate.name)) {
      setReading(null);
      setReadingProblem(`“${candidate.name}” is not a WAV or MP3 file. Convert it first, for example with Audacity or ffmpeg.`);
      return;
    }
    setReadingProblem(null);
    setReading(candidate);
  };

  const analyse = async () => {
    if (!reading || !active) return;
    const ok = await analyzeFile(reading, { baselineId: active.baseline_id, passageId: active.passage_id });
    if (ok) {
      const current = analysisStore.get().current;
      if (current) navigate(analysisPath(current.id, 'overview'));
    }
  };

  const confirmDelete = async () => {
    const target = toDelete;
    setToDelete(null);
    if (target) await deleteCustomBaseline(target.baseline_id);
  };

  return (
    <div className="page">
      <PageHead
        eyebrow="Custom passage"
        title="Compare your reading with a baseline you make yourself"
        meta={<span>Bring your own text. Read it well two or three times to make the baseline, then read it once more and see where that reading differs, with the time, the measurement and the reason.</span>}
      />

      <div className="grid-split">
        <div className="steps">
          <Panel eyebrow="Step 1" title="Your passage">
            <div className="field">
              <label className="field__label" htmlFor="custom-title">Name <span className="muted">(optional)</span></label>
              <input id="custom-title" className="input" value={title} maxLength={80} onChange={(e) => setTitle(e.target.value)} placeholder="For example: Opening of my talk" disabled={busyBaseline} />
            </div>
            <div className="field">
              <label className="field__label" htmlFor="custom-text">Passage text</label>
              <textarea
                id="custom-text" className="textarea custom-text" rows={9} value={text} disabled={busyBaseline}
                onChange={(e) => { setText(e.target.value); resetCustom(); }}
                placeholder="Paste or type the text you will read aloud. Use full sentences ending in . ! or ? so the pauses between sentences can be measured."
                aria-describedby="custom-text-hint"
              />
              <p className="field__hint custom-hint" id="custom-text-hint">
                <span className="num">{plural(stats.words, 'word')}</span> · <span className="num">{plural(stats.sentences, 'sentence')}</span>
                {' — '}{passageIssue ?? 'Good. This is checked again by the server.'}
              </p>
            </div>
          </Panel>

          <Panel
            eyebrow="Step 2"
            title="Baseline recordings"
            actions={<Segmented label="Where a recording comes from" size="sm" value={source} onChange={setSource} options={[{ value: 'file', label: 'Upload files', icon: 'upload' }, { value: 'record', label: 'Record now', icon: 'mic' }]} />}
          >
            <p className="field__hint custom-lead">
              Read the passage as you would like to be judged: steady pace, clear voice, no long gaps, same microphone and room each time.
              Two recordings work; <strong>three or more</strong> give the precise word-by-word comparison.
            </p>
            {source === 'record' ? (
              <RecorderPanel
                passage={text.trim() ? { title: title.trim() || 'Your passage', text: text.trim() } : null}
                disabled={busyBaseline || takes.length >= LIMITS.maxTakes}
                onUse={(file) => addTakes([file])}
              />
            ) : (
              <div className="custom-add">
                <Button icon="upload" onClick={() => picker.current?.click()} disabled={busyBaseline || takes.length >= LIMITS.maxTakes}>Choose recordings…</Button>
                <span className="muted">WAV or MP3, up to {LIMITS.maxTakes}. Choose several at once or one at a time.</span>
                <input ref={picker} className="sr-only" type="file" multiple aria-label="Choose baseline recordings (WAV or MP3)" accept=".wav,.mp3,audio/wav,audio/x-wav,audio/mpeg" tabIndex={-1}
                  onChange={(e) => { addTakes(Array.from(e.target.files ?? [])); e.target.value = ''; }} />
              </div>
            )}
            {problem ? <p className="form-error" role="alert"><Icon name="alert-circle" size={15} /> {problem}</p> : null}

            {takes.length > 0 ? (
              <ol className="take-list" aria-label="Baseline recordings">
                {takes.map((file, index) => (
                  <li key={`${file.name}-${file.size}-${index}`} className="take-list__item">
                    <div className="take-list__head">
                      <Icon name="file-audio" size={18} />
                      <span className="take-list__name truncate" title={file.name}>{index + 1}. {file.name}</span>
                      <span className="muted num">{fmtBytes(file.size)}</span>
                      <Button size="sm" variant="ghost" icon="x" aria-label={`Remove ${file.name}`} disabled={busyBaseline}
                        onClick={() => { setTakes((previous) => previous.filter((_, i) => i !== index)); resetCustom(); }} />
                    </div>
                    <PreviewPlayer file={file} />
                  </li>
                ))}
              </ol>
            ) : null}
            <p className="custom-count muted" aria-live="polite">
              {takes.length === 0 ? 'No recordings yet.'
                : takes.length < LIMITS.minTakes ? `${plural(takes.length, 'recording')}: add at least ${LIMITS.minTakes - takes.length} more.`
                : takes.length < LIMITS.goodTakes ? `${plural(takes.length, 'recording')}: enough, but a third gives the word-by-word comparison.`
                : `${plural(takes.length, 'recording')}: good.`}
            </p>

            <div className="runbar">
              {busyBaseline ? <BaselineProgress /> : (
                <>
                  <Button variant="primary" icon="database" disabled={!canMake} onClick={() => void make()}>Make the baseline</Button>
                  <span className="runbar__hint muted">
                    {offline ? 'The API is offline.' : passageIssue ? passageIssue : takes.length < LIMITS.minTakes ? 'Add the baseline recordings.' : 'Ready.'}
                  </span>
                </>
              )}
            </div>
            {custom.status === 'error' && custom.error ? (
              <div className="error-card" role="alert">
                <Icon name="alert-triangle" size={20} />
                <div>
                  <div className="error-card__title">The baseline could not be made</div>
                  <p>{custom.error.detail}</p>
                </div>
                <Button size="sm" variant="ghost" onClick={resetCustom}>Dismiss</Button>
              </div>
            ) : null}
            {custom.status === 'ready' && custom.result ? <ResultCard result={custom.result} /> : null}
          </Panel>

          <div ref={stepThree}>
            <Panel
              eyebrow="Step 3"
              title="Your reading"
              actions={active ? <Segmented label="Where the reading comes from" size="sm" value={readingSource} onChange={setReadingSource} options={[{ value: 'file', label: 'Upload a file', icon: 'upload' }, { value: 'record', label: 'Record now', icon: 'mic' }]} /> : null}
            >
              {!active ? (
                <div className="inline-state">
                  <Icon name="info" size={18} />
                  <div>
                    <strong>Make a baseline first.</strong>
                    <p>Once a baseline exists (step 2), read the same passage once more here and it is compared with it.</p>
                  </div>
                </div>
              ) : (
                <>
                  <p className="field__hint custom-lead">
                    Compared with <strong>{active.passage_title ?? active.baseline_id}</strong>. Read the same passage, as you would deliver it.
                  </p>
                  {readingSource === 'record' ? (
                    <RecorderPanel
                      passage={active.passage_text ? { title: active.passage_title ?? active.baseline_id, text: active.passage_text } : null}
                      disabled={busyAnalysis}
                      onUse={(file) => { acceptReading(file); setReadingSource('file'); }}
                    />
                  ) : (
                    <FileDrop file={reading} onFile={acceptReading} onClear={() => { setReading(null); setReadingProblem(null); }} />
                  )}
                  {readingProblem ? <p className="form-error" role="alert"><Icon name="alert-circle" size={15} /> {readingProblem}</p> : null}
                  <div className="runbar">
                    {busyAnalysis ? <Progress /> : (
                      <>
                        <Button variant="primary" icon="gauge" disabled={!reading || offline} onClick={() => void analyse()}>Analyse my reading</Button>
                        <span className="runbar__hint muted">{!reading ? 'Choose or record your reading to begin.' : offline ? 'The API is offline.' : 'Ready.'}</span>
                      </>
                    )}
                  </div>
                  {analysis.status === 'error' && analysis.error ? (
                    <div className="error-card" role="alert">
                      <Icon name="alert-triangle" size={20} />
                      <div>
                        <div className="error-card__title">The analysis could not be completed</div>
                        <p>{analysis.error.detail}</p>
                      </div>
                      <Button size="sm" variant="ghost" onClick={dismissError}>Dismiss</Button>
                    </div>
                  ) : null}
                </>
              )}
            </Panel>
          </div>
        </div>

        <div className="steps steps--side">
          <Panel eyebrow="Your passages" title="Custom baselines" actions={catalog.status === 'loading' ? <span className="spinner" aria-label="Loading" /> : null}>
            <CustomList items={customBaselines} activeId={activeId} onUse={(id) => { setActiveId(id); setReading(null); stepThree.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }); }} onDelete={setToDelete} />
            <p className="field__hint">They are stored on the server as statistics and text only, never as audio. They also appear on the New analysis page.</p>
          </Panel>
          <Panel eyebrow="Good to know" title="How the comparison works">
            <ul className="custom-notes">
              <li>The baseline is <em>your own</em> good reading of <em>this</em> text, so the comparison is fair for this content and this voice.</li>
              <li>Pace, loudness, pauses and pitch are compared word by word with how you read the same words in the baseline recordings.</li>
              <li>A reading that is only slightly different is not flagged: with a few baseline recordings, ordinary variation is expected.</li>
              <li>The thresholds are initial values and have not been calibrated on recorded data; treat the findings as indicative.</li>
            </ul>
          </Panel>
        </div>
      </div>

      <Dialog open={toDelete !== null} onClose={() => setToDelete(null)} title="Delete this custom baseline?">
        <p>“{toDelete?.passage_title ?? toDelete?.baseline_id}” and its passage text will be removed from the server. Analyses you already made stay in your library.</p>
        <div className="dialog__actions">
          <Button onClick={() => setToDelete(null)}>Keep it</Button>
          <Button variant="primary" icon="trash" onClick={() => void confirmDelete()}>Delete</Button>
        </div>
      </Dialog>
    </div>
  );
}
