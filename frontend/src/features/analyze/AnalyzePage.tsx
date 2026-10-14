import { useEffect, useState } from 'react';
import type { SampleIndex } from '@/api/types';
import { isSupportedAudioName, type ApiErrorCode } from '@/api/client';
import { Icon } from '@/components/Icon';
import { PageHead } from '@/components/page';
import { Button, Chip, Panel, Segmented } from '@/components/ui';
import { fmtBytes, fmtDuration, fmtNum, fmtRelative, plural } from '@/lib/format';
import { safeStorage } from '@/lib/store';
import { analysisPath, navigate } from '@/app/router';
import { analysisStore, analyzeFile, cancelLoading, dismissError, loadSamples, useAnalysis } from '@/state/analysis';
import { refreshCatalog, useCatalog, useConnection } from '@/state/connection';
import { useHistory } from '@/state/history';
import { FileDrop } from './FileDrop';
import { RecorderPanel } from './RecorderPanel';
import { SampleCard } from './SampleCard';

const LAST_BASELINE = 'sa.lastBaseline';

const ERROR_TITLE: Partial<Record<ApiErrorCode, string>> = {
  UNSUPPORTED_AUDIO_FORMAT: 'That file type is not supported',
  FILE_TOO_LARGE: 'The file is too large',
  AUDIO_TOO_LONG: 'The recording is too long',
  BASELINE_NOT_FOUND: 'That baseline is not installed',
  VALIDATION_ERROR: 'The request was not valid',
  CONFIG_VERSION_MISMATCH: 'The configuration version does not match',
  PROCESSING_ERROR: 'The analysis could not be completed',
  NETWORK_ERROR: 'The API could not be reached',
  BAD_RESPONSE: 'The API answered unexpectedly',
  HTTP_ERROR: 'The server reported an error',
};

export function Progress() {
  const state = useAnalysis();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, []);
  const p = state.progress;
  if (!p) return null;
  const elapsed = Math.max(0, (now - p.startedAt) / 1000);
  const uploading = p.phase === 'uploading';
  const share = p.total > 0 ? p.loaded / p.total : 0;
  return (
    <div className="progress" role="status" aria-live="polite">
      <div className="progress__head">
        <span className="progress__phase">{uploading ? 'Uploading the recording' : p.phase === 'loading' ? 'Opening the analysis' : 'Analysing on the server'}</span>
        <span className="num progress__time">{fmtNum(elapsed, 0)} s</span>
      </div>
      <div className={`progress__bar ${uploading ? '' : 'is-indeterminate'}`} aria-hidden="true"><i style={uploading ? { width: `${share * 100}%` } : undefined} /></div>
      <p className="progress__text">
        {uploading
          ? `${fmtBytes(p.loaded)} of ${fmtBytes(p.total)} sent.`
          : p.phase === 'loading'
            ? 'Fetching the stored result.'
            : 'Transcribing, aligning and measuring. The server reports no finer progress; longer recordings take longer. The result opens here when it is ready.'}
      </p>
      <Button size="sm" variant="ghost" icon="x" onClick={cancelLoading}>Cancel</Button>
    </div>
  );
}

export function AnalyzePage() {
  const analysis = useAnalysis();
  const catalog = useCatalog();
  const connection = useConnection();
  const history = useHistory();
  const [file, setFile] = useState<File | null>(null);
  const [fileProblem, setFileProblem] = useState<string | null>(null);
  const [baselineId, setBaselineId] = useState<string>(() => safeStorage.get(LAST_BASELINE) ?? '');
  const [useManual, setUseManual] = useState(false);
  const [manual, setManual] = useState('');
  const [showPassage, setShowPassage] = useState(false);
  const [source, setSource] = useState<'file' | 'record'>('file');
  const [samples, setSamples] = useState<SampleIndex | null>(null);

  useEffect(() => {
    if (catalog.status === 'idle' || catalog.status === 'error') void refreshCatalog();
    let cancelled = false;
    loadSamples().then((s) => !cancelled && setSamples(s)).catch(() => undefined);
    return () => { cancelled = true; };
    // Load once on arrival; the catalogue is refreshed again by the retry button.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const baselines = catalog.data?.baselines ?? [];
  const selected = baselines.find((b) => b.baseline_id === baselineId) ?? baselines[0] ?? null;
  useEffect(() => {
    if (selected && selected.baseline_id !== baselineId) setBaselineId(selected.baseline_id);
  }, [selected, baselineId]);

  const busy = analysis.status === 'loading';
  const offline = connection.status === 'offline';
  const canRun = !!file && !!selected && !busy && !offline && (!useManual || manual.trim().length > 0);

  const accept = (candidate: File | undefined) => {
    if (!candidate) return;
    if (!isSupportedAudioName(candidate.name)) {
      setFile(null);
      setFileProblem(`“${candidate.name}” is not a WAV or MP3 file. Convert it first, for example with Audacity or ffmpeg.`);
      return;
    }
    setFileProblem(null);
    setFile(candidate);
  };

  const run = async () => {
    if (!file || !selected) return;
    safeStorage.set(LAST_BASELINE, selected.baseline_id);
    const ok = await analyzeFile(file, { baselineId: selected.baseline_id, passageId: selected.passage_id, manualTranscript: useManual ? manual : undefined });
    if (ok) {
      const current = analysisStore.get().current;
      if (current) navigate(analysisPath(current.id, 'overview'));
    }
  };

  return (
    <div className="page">
      <PageHead
        eyebrow="New analysis"
        title="Where did the delivery drift from the baseline?"
        meta={<span>Upload a recording of a passage. It is compared with a baseline recording of the same passage, and every deviation is tied to a time, a measurement, a reason and a suggestion.</span>}
      />

      <div className="grid-split">
        <div className="steps">
          <Panel
            eyebrow="Step 1"
            title="Recording"
            actions={<Segmented label="Where the recording comes from" size="sm" value={source} onChange={setSource} options={[{ value: 'file', label: 'Upload a file', icon: 'upload' }, { value: 'record', label: 'Record now', icon: 'mic' }]} />}
          >
            {source === 'record' ? (
              <RecorderPanel
                passage={selected?.passage_text ? { title: selected.passage_title ?? selected.passage_id, text: selected.passage_text } : null}
                disabled={busy}
                onUse={(recorded) => { accept(recorded); setSource('file'); }}
              />
            ) : (
              <FileDrop file={file} onFile={accept} onClear={() => { setFile(null); setFileProblem(null); }} />
            )}
            {source === 'file' && fileProblem ? <p className="form-error" role="alert"><Icon name="alert-circle" size={15} /> {fileProblem}</p> : null}
          </Panel>

          <Panel
            eyebrow="Step 2"
            title="Baseline and passage"
            actions={catalog.status === 'loading' ? <span className="spinner" aria-label="Loading baselines" /> : null}
          >
            {baselines.length > 0 && selected ? (
              <div className="field">
                <label className="field__label" htmlFor="baseline">Compare with</label>
                <select id="baseline" className="select" value={selected.baseline_id} onChange={(e) => setBaselineId(e.target.value)} disabled={busy}>
                  {baselines.map((b) => (
                    <option key={b.baseline_id} value={b.baseline_id}>{b.passage_title ?? b.baseline_id} · {plural(b.n_baseline_recordings, 'recording')}{b.custom ? ' · custom' : ''}</option>
                  ))}
                </select>
                <p className="field__hint">The recording should be a reading of this passage. A baseline is the effective delivery of the same content, so the passage decides which comparison is fair.</p>
                {selected.thin_rate_statistics || selected.thin_pause_statistics ? (
                  <p className="form-warn"><Chip tone="warn" icon="alert-triangle">Thin statistics</Chip> This baseline has few observations for {[selected.thin_rate_statistics ? 'speech rate' : null, selected.thin_pause_statistics ? 'pauses' : null].filter(Boolean).join(' and ')}; expect noisier z-scores.</p>
                ) : null}
                {selected.passage_text ? (
                  <div className="passage-box">
                    <button type="button" className="link-btn passage-box__toggle" aria-expanded={showPassage} onClick={() => setShowPassage((v) => !v)}>
                      {showPassage ? 'Hide the passage' : `Show the passage to read${selected.passage_word_count ? ` (${selected.passage_word_count} words)` : ''}`}
                    </button>
                    {showPassage ? <p className="passage passage--small">{selected.passage_text}</p> : null}
                  </div>
                ) : null}
              </div>
            ) : catalog.status === 'error' || offline ? (
              <div className="inline-state">
                <Icon name="alert-circle" size={18} />
                <div>
                  <strong>{offline ? 'The API is offline.' : 'The baselines could not be loaded.'}</strong>
                  <p>{catalog.error?.detail ?? 'Start the backend to analyse a recording. The demo samples work without it.'}</p>
                  <Button size="sm" variant="secondary" icon="refresh" onClick={() => void refreshCatalog()}>Try again</Button>
                </div>
              </div>
            ) : catalog.status === 'ready' ? (
              <div className="inline-state">
                <Icon name="database" size={18} />
                <div>
                  <strong>No baseline is installed on this server yet.</strong>
                  <p>A baseline is built from recordings of a reference delivery of the passage (see docs/methodology/recording-protocol.md). Until one is installed, open a demo sample to see what an analysis looks like.</p>
                  {(catalog.data?.unavailable?.length ?? 0) > 0 ? <p>{plural(catalog.data?.unavailable?.length ?? 0, 'baseline file')} exist but cannot be used: {catalog.data?.unavailable?.map((u) => `${u.baseline_id} (${u.reason.replace(/_/g, ' ')})`).join(', ')}.</p> : null}
                </div>
              </div>
            ) : <p className="muted">Loading baselines…</p>}

            <details className="advanced" open={useManual} onToggle={(e) => setUseManual((e.currentTarget as HTMLDetailsElement).open)}>
              <summary>Advanced: supply the transcript yourself</summary>
              <div className="field">
                <label className="field__label" htmlFor="manual">Transcript of the recording</label>
                <textarea id="manual" className="textarea" rows={4} value={manual} onChange={(e) => setManual(e.target.value)} placeholder="Paste exactly what was said. Speech recognition is skipped; words are still aligned to the audio." />
                <p className="field__hint">Useful when the recognised text would differ from what was said, for example with names or accents. Leave this closed to use speech recognition.</p>
              </div>
            </details>
          </Panel>

          <div className="runbar">
            {busy ? <Progress /> : (
              <>
                <Button variant="primary" icon="gauge" disabled={!canRun} onClick={() => void run()}>Analyse recording</Button>
                <span className="runbar__hint muted">
                  {!file ? 'Choose a recording to begin.' : !selected ? 'No baseline available.' : offline ? 'The API is offline.' : useManual && !manual.trim() ? 'Enter the transcript or close the advanced option.' : 'Ready.'}
                </span>
              </>
            )}
          </div>

          {analysis.status === 'error' && analysis.error ? (
            <div className="error-card" role="alert">
              <Icon name="alert-triangle" size={20} />
              <div>
                <div className="error-card__title">{ERROR_TITLE[analysis.error.code] ?? 'Something went wrong'}</div>
                <p>{analysis.error.detail}</p>
              </div>
              <Button size="sm" variant="ghost" onClick={dismissError}>Dismiss</Button>
            </div>
          ) : null}
        </div>

        <div className="steps steps--side">
          <Panel eyebrow="No recording at hand?" title="Try a demo sample">
            <p className="sample-note">Synthetic voice, deliberate flaws, analysed by the real pipeline. No backend or baseline is needed to open one.</p>
            {samples ? (
              <ul className="samples">{samples.samples.map((s) => <SampleCard key={s.id} sample={s} />)}</ul>
            ) : <p className="muted">Loading samples…</p>}
          </Panel>

          {history.length > 0 ? (
            <Panel eyebrow="Recent" title="Pick up where you left off" flush>
              <ul className="recent">
                {history.slice(0, 4).map((h) => (
                  <li key={h.id}>
                    <button type="button" className="recent__item" onClick={() => navigate(analysisPath(h.id, 'overview'))}>
                      <span className="recent__title truncate">{h.title}</span>
                      <span className="recent__meta num">{fmtNum(h.composite, 1)} · {plural(h.flawCount, 'finding')} · {fmtDuration(h.durationS)}</span>
                      <span className="recent__when muted">{fmtRelative(h.openedAt)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
        </div>
      </div>
    </div>
  );
}
