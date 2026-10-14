import { useEffect, useMemo, useState } from 'react';
import type { AnalysisNote, Flaw, SampleIndex } from '@/api/types';
import { ScoreRadar, type RadarDim } from '@/charts/ScoreRadar';
import { TimelineStack } from '@/charts/TimelineStack';
import { Icon } from '@/components/Icon';
import { Fact, Figure, HashValue, PageHead, SeverityBar, SourceChip } from '@/components/page';
import { Button, Chip, FlawTag, Meter, Panel } from '@/components/ui';
import { evidenceHeadline } from '@/lib/evidence';
import { FLAW_ORDER, SCORE_DIMENSIONS } from '@/lib/flawMeta';
import { fmtDuration, fmtLevel, fmtNum, plural, titleCase } from '@/lib/format';
import { NOTE_CATEGORY_LABEL, NOTE_CATEGORY_ORDER, NOTE_ICON, noteMeta, type NoteCategory } from '@/lib/notesMeta';
import { analysedSpan, findFlaw, flawsBySeverity, recordingDuration } from '@/lib/result';
import { useSettings, useTimecode } from '@/lib/settings';
import { useStore } from '@/lib/store';
import { FULL, windowAround } from '@/lib/time';
import { analysisPath, navigate } from '@/app/router';
import { goToFlaw, exportResultJson } from '@/state/actions';
import { loadSamples, type LoadedAnalysis } from '@/state/analysis';
import { playerStore, seek } from '@/state/player';
import { selectFlaw, selectionStore, setView } from '@/state/ui';

/** Splits the backend's summary into sentences without touching the text (a full stop followed by a capital starts a new one). */
function sentences(text: string): string[] {
  return text.split(/(?<=\.)\s+(?=[A-Z])/).map((s) => s.trim()).filter(Boolean);
}

// ---- score -----------------------------------------------------------------------------------------------------------------
function ScoreRule({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="scale" role="img" aria-label={`Deviation score ${fmtNum(value, 1)} on a scale from 0 to 100`}>
      <div className="scale__track">
        <div className="scale__fill" style={{ width: `${pct}%` }} />
        {Array.from({ length: 21 }, (_, i) => <i key={i} className={i % 10 === 0 ? 'is-major' : i % 2 === 0 ? 'is-mid' : ''} style={{ left: `${i * 5}%` }} />)}
        <div className="scale__needle" style={{ left: `${pct}%` }} />
      </div>
      <div className="scale__labels num" aria-hidden="true"><span>0</span><span>50</span><span>100</span></div>
    </div>
  );
}

function ScoreBlock({ analysis }: { analysis: LoadedAnalysis }) {
  const { result } = analysis;
  const { composite_score: score, scoring_version: version } = result.scores;
  const span = analysedSpan(result);
  return (
    <section className="score" aria-label="Deviation score">
      <div className="eyebrow">Deviation score</div>
      <div className="score__value">
        <span className="score__num">{fmtNum(score, 1)}</span>
        <span className="score__of num">/ 100</span>
      </div>
      <ScoreRule value={score} />
      <p className="score__caption">
        100 means no deviation from the baseline was detected. It describes how this delivery differs from the baseline, not how good the speech is.
      </p>
      <dl className="score__facts">
        <div><dt>Findings</dt><dd className="num">{result.flaws.length}</dd></div>
        <div><dt>Analysed</dt><dd className="num">{fmtNum(span.end - span.start, 1)} s</dd></div>
        <div><dt>Scoring</dt><dd className="num">v{version}</dd></div>
      </dl>
    </section>
  );
}

function Readout({ analysis }: { analysis: LoadedAnalysis }) {
  const { result } = analysis;
  const parts = sentences(result.overall_summary ?? '');
  const methods = [...new Set(result.flaws.map((f) => f.explanation_method))];
  const counts = FLAW_ORDER.map((type) => ({ type, n: result.flaws.filter((f) => f.type === type).length })).filter((c) => c.n > 0);
  return (
    <section className="readout" aria-label="Readout">
      <div className="eyebrow">Readout</div>
      {parts.length > 0 ? (
        <>
          <p className="readout__lead">{parts[0]}</p>
          {parts.length > 1 ? <p className="readout__rest">{parts.slice(1).join(' ')}</p> : null}
        </>
      ) : <p className="readout__rest">The backend returned no summary for this analysis.</p>}
      <div className="readout__foot">
        {counts.map((c) => (
          <span key={c.type} className="readout__count"><FlawTag type={c.type} /><span className="num">× {c.n}</span></span>
        ))}
        {result.flaws.length === 0 ? <Chip tone="good" icon="check">No deviation flagged</Chip> : null}
        <span className="readout__spacer" />
        {methods.length > 0 ? <Chip icon="shield-check">{methods.map((m) => (m === 'template' ? 'Template explanations' : `Explanations: ${m}`)).join(', ')}</Chip> : null}
      </div>
    </section>
  );
}

// ---- score breakdown ---------------------------------------------------------------------------------------------------------
function Breakdown({ analysis }: { analysis: LoadedAnalysis }) {
  const { result } = analysis;
  const scores = result.scores.feature_scores;
  const [activeKey, setActiveKey] = useState<string | null>(null);

  const dims: RadarDim[] = SCORE_DIMENSIONS.map((dim) => {
    const entry = scores[dim.key];
    const note = result.notes?.find((n) => n.code === `${dim.key}_not_scored` || n.code === `${dim.key}_unavailable`);
    return entry
      ? { key: dim.key, label: dim.label, score: entry.score, weight: entry.weight, flawCount: entry.flaw_count, penalty: entry.penalty_total }
      : { key: dim.key, label: dim.label, score: null, weight: 0, flawCount: 0, penalty: 0, reason: note ? note.message : undefined };
  });

  /** A dimension opens its strongest finding (the findings of its flaw types, strongest first). */
  const open = (key: string) => {
    const dim = SCORE_DIMENSIONS.find((d) => d.key === key);
    const strongest = dim ? flawsBySeverity(result.flaws.filter((f) => (dim.flaws as readonly string[]).includes(f.type)))[0] : undefined;
    if (!strongest) return;
    selectFlaw(strongest.flaw_id);
    navigate(analysisPath(analysis.id, 'flaws', strongest.flaw_id));
  };

  return (
    <Panel eyebrow="How the score is made" title="Score profile">
      <div className="profile">
      <ScoreRadar
        dims={dims} activeKey={activeKey} onActive={setActiveKey} onOpen={open} openHint="Click to open its strongest finding"
        label="Score profile: the score of each dimension on a scale from 0 to 100, where the outer ring is no deviation from the baseline"
      />
      <ul className="dims">
        {SCORE_DIMENSIONS.map((dim) => {
          const entry = scores[dim.key];
          const note = result.notes?.find((n) => n.code === `${dim.key}_not_scored` || n.code === `${dim.key}_unavailable`);
          const on = activeKey === dim.key;
          if (!entry) {
            return (
              <li key={dim.key} className={`dim dim--off ${on ? 'is-active' : ''}`} onPointerEnter={() => setActiveKey(dim.key)} onPointerLeave={() => setActiveKey(null)}>
                <div className="dim__head"><span className="dim__name">{dim.label}</span><span className="dim__value muted">not scored</span></div>
                <div className="meter meter--off" aria-hidden="true" />
                <p className="dim__why">{note ? note.message : 'The backend did not evaluate this dimension for this analysis.'}</p>
              </li>
            );
          }
          return (
            <li key={dim.key} className={`dim ${on ? 'is-active' : ''}`} onPointerEnter={() => setActiveKey(dim.key)} onPointerLeave={() => setActiveKey(null)}>
              <div className="dim__head">
                <span className="dim__name">{dim.label}</span>
                <span className="dim__value num">{fmtNum(entry.score, 1)}</span>
              </div>
              <Meter value={entry.score} label={`${dim.label} score`} tone={entry.flaw_count > 0 ? 'warn' : 'brand'} />
              <div className="dim__meta num">
                <span>weight {fmtNum(entry.weight * 100, 0)} %</span>
                <span>{plural(entry.flaw_count, 'finding')}</span>
                {entry.penalty_total > 0 ? <span>penalty −{fmtNum(entry.penalty_total, 1)}</span> : <span>no penalty</span>}
              </div>
            </li>
          );
        })}
      </ul>
      </div>
      <p className="panel__foot-note">Each dimension starts at 100 and loses points for every finding, in proportion to its severity and reliability. A dimension that could not be evaluated is left out, never scored as perfect, and the remaining weights are renormalised: the weights shown are those effective weights. The composite is their weighted sum, computed by the backend.</p>
    </Panel>
  );
}

// ---- findings --------------------------------------------------------------------------------------------------------------
function Findings({ analysis }: { analysis: LoadedAnalysis }) {
  const tc = useTimecode();
  const hasAudio = useStore(playerStore, (s) => s.src !== null);
  const flaws = useMemo(() => flawsBySeverity(analysis.result.flaws), [analysis.result.flaws]);
  const shown = flaws.slice(0, 6);
  return (
    <Panel
      eyebrow="Where delivery deviated"
      title={flaws.length === 0 ? 'No findings' : `Findings, strongest first`}
      actions={flaws.length > 0 ? <Button size="sm" variant="ghost" iconRight="arrow-right" onClick={() => navigate(analysisPath(analysis.id, 'flaws'))}>All {flaws.length}</Button> : null}
      flush
    >
      {flaws.length === 0 ? (
        <div className="ledger-empty">
          <Icon name="check" size={18} />
          <p>No stretch of this recording crossed a detection rule against the baseline. The notes below say what was and was not checked.</p>
        </div>
      ) : (
        <ol className="ledger">
          {shown.map((f, i) => (
            <li key={f.flaw_id}>
              <a
                className="ledger__row"
                href={`#${analysisPath(analysis.id, 'flaws', f.flaw_id)}`}
                onClick={(e) => { e.preventDefault(); selectFlaw(f.flaw_id); navigate(analysisPath(analysis.id, 'flaws', f.flaw_id)); }}
              >
                <span className="ledger__no num">{String(i + 1).padStart(2, '0')}</span>
                <span className="ledger__main">
                  <span className="ledger__line">
                    <FlawTag type={f.type} />
                    <span className="ledger__when num">{tc.range(f.start_s, f.end_s)}</span>
                  </span>
                  <span className="ledger__evidence num">{evidenceHeadline(f)}</span>
                </span>
                <span className="ledger__sev"><SeverityBar value={f.severity} /></span>
                <Icon name="chevron-right" size={16} />
              </a>
              {hasAudio ? (
                <button type="button" className="ledger__play icon-btn icon-btn--small" aria-label={`Play ${f.flaw_id}`} title="Play this stretch" onClick={() => goToFlaw(f, { play: true })}>
                  <Icon name="play" size={13} />
                </button>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

// ---- notes ---------------------------------------------------------------------------------------------------------------------
function Notes({ notes }: { notes: readonly AnalysisNote[] }) {
  const grouped = NOTE_CATEGORY_ORDER
    .map((category) => ({ category, items: notes.filter((n) => noteMeta(n.code).category === category) }))
    .filter((g) => g.items.length > 0);
  const cautions = notes.filter((n) => noteMeta(n.code).level === 'caution').length;
  return (
    <Panel eyebrow="Read before relying on this result" title="Notes and limitations" actions={notes.length > 0 ? <Chip tone={cautions ? 'warn' : 'neutral'}>{plural(notes.length, 'note')}{cautions ? ` · ${cautions} caution` : ''}</Chip> : null}>
      {notes.length === 0 ? <p className="muted">The backend attached no notes to this analysis.</p> : (
        <div className="notes">
          {grouped.map((g) => (
            <section key={g.category} className="notes__group">
              <h3 className="eyebrow">{NOTE_CATEGORY_LABEL[g.category as NoteCategory]}</h3>
              <ul>
                {g.items.map((n) => {
                  const meta = noteMeta(n.code);
                  return (
                    <li key={n.code} className={`note note--${meta.level}`}>
                      <Icon name={NOTE_ICON[meta.level]} size={16} />
                      <div>
                        <div className="note__title">{meta.title}</div>
                        <p className="note__text">{n.message}</p>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Panel>
  );
}

// ---- provenance -----------------------------------------------------------------------------------------------------------------
function Provenance({ analysis }: { analysis: LoadedAnalysis }) {
  const { result } = analysis;
  const meta = result.processing_meta;
  return (
    <Panel eyebrow="Reproducibility" title="Provenance">
      <dl className="facts">
        <Fact label="Analysis id"><HashValue value={result.analysis_id} length={13} what="analysis id" /></Fact>
        <Fact label="Recording"><HashValue value={result.audio.sha256} length={13} what="recording hash" /></Fact>
        <Fact label="Audio" hint={`peak ${fmtLevel(result.audio.peak_dbfs, 1)} dBFS`}>{fmtNum(result.audio.sample_rate_hz / 1000, 0)} kHz · {result.audio.channels === 1 ? 'mono' : `${result.audio.channels} ch`}</Fact>
        <Fact label="Baseline" hint={`dataset ${result.baseline.dataset_version}`}>{result.baseline.baseline_id}</Fact>
        <Fact label="Baseline hash"><HashValue value={result.baseline.sha256} length={13} what="baseline hash" /></Fact>
        <Fact label="Configuration" hint={`v${result.config_version}`}>{result.config_fingerprint ? <HashValue value={result.config_fingerprint} length={13} what="configuration fingerprint" /> : '-'}</Fact>
        <Fact label="Pipeline" hint={`scoring v${result.scores.scoring_version}`}>v{result.pipeline_version}</Fact>
        <Fact label="Transcript" hint={meta.whisper_model ? `model ${meta.whisper_model}` : undefined}>{meta.transcript_source === 'manual' ? 'supplied manually' : 'speech recognition'}</Fact>
        <Fact label="Alignment">{titleCase(result.alignment_method)}</Fact>
        <Fact label="Processing" hint={meta.cached ? 'served from the result store' : 'computed for this request'}>{fmtNum(meta.processing_time_s, 1)} s</Fact>
      </dl>
      <p className="panel__foot-note">The same recording, baseline and configuration give the same id and the same numbers. The id and hashes above identify exactly what was measured.</p>
    </Panel>
  );
}

// ---- sample banner ---------------------------------------------------------------------------------------------------------------
function SampleBanner({ analysis }: { analysis: LoadedAnalysis }) {
  const [index, setIndex] = useState<SampleIndex | null>(null);
  const tc = useTimecode();
  useEffect(() => {
    let cancelled = false;
    loadSamples().then((i) => !cancelled && setIndex(i)).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);
  const sample = analysis.sample;
  if (!sample) return null;
  return (
    <aside className="banner" aria-label="About this sample">
      <div className="banner__icon"><Icon name="flask" size={20} /></div>
      <div className="banner__body">
        <div className="banner__title">Synthetic demonstration</div>
        <p>{index?.note ?? 'A synthetic voice read the passage with deliberate, known flaws. Every number is produced by the real analysis code.'}</p>
        <ul className="truth">
          {sample.injected.length === 0 ? <li className="truth__none">No flaw was injected: this take is the control.</li> : null}
          {sample.injected.map((t, i) => (
            <li key={i}>
              <FlawTag type={t.type} />
              <span className="num">{tc.range(t.start_s, t.end_s)}</span>
              {t.detected ? <Chip tone="good" icon="check">detected</Chip> : <Chip tone="warn" icon="alert-triangle">not detected</Chip>}
            </li>
          ))}
          {sample.extra_detections > 0 ? <li className="truth__none">{plural(sample.extra_detections, 'additional finding')} the generator did not inject.</li> : null}
        </ul>
        {index ? (
          <details className="banner__more">
            <summary>How this sample was chosen, and what it does not show</summary>
            <p>{index.selection_note}</p>
            <p>
              <strong>Calibration warning.</strong> {index.diagnostics.clean_takes_flagged} of {index.diagnostics.clean_takes_probed} clean synthetic takes were flagged by the current thresholds. {index.diagnostics.comment}
            </p>
          </details>
        ) : null}
      </div>
    </aside>
  );
}

// ---- page ----------------------------------------------------------------------------------------------------------------------
export function OverviewPage({ analysis }: { analysis: LoadedAnalysis }) {
  const { result } = analysis;
  const settings = useSettings();
  const tc = useTimecode();
  const selectedId = useStore(selectionStore, (s) => s.flawId);
  const duration = recordingDuration(result);
  const span = analysedSpan(result);
  const trimmed = span.start > 0.05 || span.end < duration - 0.05;
  const selected: Flaw | null = findFlaw(result, selectedId);
  const view = useMemo(() => FULL(duration), [duration]);

  const openInTimeline = (time: number) => {
    setView(windowAround(time - 4, time + 4, duration, 0));
    if (playerStore.get().src) seek(time);
    navigate(analysisPath(analysis.id, 'timeline'));
  };

  return (
    <div className="page page--overview">
      <PageHead
        eyebrow={<>Analysis <span aria-hidden="true">·</span> <SourceChip source={analysis.source} /></>}
        title={analysis.title}
        meta={(
          <>
            <span>{fmtDuration(duration)}</span>
            {trimmed ? <span>analysed {tc.range(span.start, span.end)}</span> : null}
            <span>{plural(result.alignment.length, 'word')}</span>
            <span>baseline <span className="num">{result.baseline.baseline_id}</span></span>
          </>
        )}
        actions={(
          <>
            <Button variant="ghost" icon="download" onClick={exportResultJson}>Export JSON</Button>
            <Button variant="secondary" icon="printer" onClick={() => navigate(analysisPath(analysis.id, 'report'))}>Report</Button>
            <Button variant="primary" icon="gantt" onClick={() => navigate(analysisPath(analysis.id, 'timeline'))}>Open timeline</Button>
          </>
        )}
      />

      <SampleBanner analysis={analysis} />

      <div className="hero">
        <ScoreBlock analysis={analysis} />
        <Readout analysis={analysis} />
      </div>

      <Figure
        no={1}
        title="Delivery against the baseline"
        note="Shaded bands are the baseline mean ± 1 and 2 standard deviations. Click a finding to read its evidence, or anywhere on the plot to open that moment in the timeline."
        actions={<Button size="sm" variant="ghost" iconRight="arrow-right" onClick={() => navigate(analysisPath(analysis.id, 'timeline'))}>Timeline</Button>}
      >
        <TimelineStack
          analysis={analysis}
          lanes={['flaws', 'rate', 'loudness', 'pauses']}
          view={view}
          compact
          selected={selected}
          onSelect={(f) => { selectFlaw(f.flaw_id); navigate(analysisPath(analysis.id, 'flaws', f.flaw_id)); }}
          onPlotClick={openInTimeline}
          showTruth={settings.showGroundTruth}
          label="Delivery against the baseline: findings, speech rate, loudness and pauses over the whole recording"
        />
      </Figure>

      <Findings analysis={analysis} />
      <Breakdown analysis={analysis} />

      <div className="grid-split grid-split--even">
        <Notes notes={result.notes ?? []} />
        <Provenance analysis={analysis} />
      </div>
    </div>
  );
}
