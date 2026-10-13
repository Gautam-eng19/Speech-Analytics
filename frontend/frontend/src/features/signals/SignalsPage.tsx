import { useMemo, useState } from 'react';
import type { AnalysisResult, PauseEvent } from '@/api/types';
import { laneHeights, type LaneKey } from '@/charts/geometry';
import { TimelineStack } from '@/charts/TimelineStack';
import { Icon } from '@/components/Icon';
import { Fact, Figure, PageHead } from '@/components/page';
import { Button, Chip, Panel, ScrollRegion, Segmented } from '@/components/ui';
import { fmtLevel, fmtNum, titleCase } from '@/lib/format';
import { findFlaw, recordingDuration } from '@/lib/result';
import { useTimecode } from '@/lib/settings';
import { useStore } from '@/lib/store';
import { FULL, span } from '@/lib/time';
import { analysisPath, navigate } from '@/app/router';
import type { LoadedAnalysis } from '@/state/analysis';
import { playerStore, seek } from '@/state/player';
import { selectionStore, selectFlaw, setView, viewStore } from '@/state/ui';

function noteFor(result: AnalysisResult, code: string): string | null {
  return result.notes?.find((n) => n.code === code)?.message ?? null;
}

/** One signal: its chart on the shared time window, what it is compared with, and the values as a table for those who prefer one. */
function SignalFigure({
  no, analysis, lane, height, title, note, facts, table,
}: {
  no: number;
  analysis: LoadedAnalysis;
  lane: LaneKey;
  height: number;
  title: string;
  note: string;
  facts?: React.ReactNode;
  table?: React.ReactNode;
}) {
  const view = useStore(viewStore, (v) => v);
  const selectedId = useStore(selectionStore, (s) => s.flawId);
  const selected = findFlaw(analysis.result, selectedId);
  const base = laneHeights(false);
  return (
    <Figure no={no} title={title} note={note}>
      <TimelineStack
        analysis={analysis}
        lanes={lane === 'flaws' ? ['flaws'] : ['flaws', lane]}
        heights={{ [lane]: height, flaws: base.flaws }}
        view={view}
        onView={setView}
        selected={selected}
        onSelect={(f) => selectFlaw(selectedId === f.flaw_id ? null : f.flaw_id)}
        onPlotClick={(t) => { if (playerStore.get().src) seek(t); }}
        showTruth={false}
        label={`${title}, with the findings above it`}
      />
      {facts ? <dl className="signal-facts">{facts}</dl> : null}
      {table ? (
        <details className="signal-table">
          <summary>Show the values as a table</summary>
          {table}
        </details>
      ) : null}
    </Figure>
  );
}

function PauseTable({ analysis }: { analysis: LoadedAnalysis }) {
  const tc = useTimecode();
  const { result } = analysis;
  const [sort, setSort] = useState<'time' | 'length'>('time');
  const rows = useMemo(() => {
    const events = [...result.features.pause_events];
    return sort === 'time' ? events.sort((a, b) => a.start_s - b.start_s) : events.sort((a, b) => b.duration_s - a.duration_s);
  }, [result.features.pause_events, sort]);
  const flagged = (e: PauseEvent) => result.flaws.find((f) => f.type === 'excessive_pause' && f.start_s <= e.end_s + 0.02 && f.end_s >= e.start_s - 0.02) ?? null;
  return (
    <Panel
      eyebrow="Every silence between words"
      title={`${rows.length} pauses`}
      actions={<Segmented label="Sort pauses" size="sm" value={sort} onChange={setSort} options={[{ value: 'time', label: 'By time' }, { value: 'length', label: 'By length' }]} />}
      flush
    >
      <ScrollRegion label="Pauses">
        <table className="table">
          <thead>
            <tr><th>#</th><th>From</th><th>To</th><th className="r">Length</th><th>Between</th><th>Detected by</th><th>Finding</th></tr>
          </thead>
          <tbody>
            {rows.map((e, i) => {
              const hit = flagged(e);
              return (
                <tr key={`${e.start_s}-${i}`} className={hit ? 'is-flagged' : ''} style={hit ? { ['--c' as string]: `var(--f-${hit.type})` } : undefined}>
                  <td className="num muted">{i + 1}</td>
                  <td className="num">{tc.at(e.start_s, 2)}</td>
                  <td className="num">{tc.at(e.end_s, 2)}</td>
                  <td className="num r">{fmtNum(e.duration_s, 2)} s</td>
                  <td>{e.boundary_type === 'unknown' ? <span className="muted">unknown</span> : titleCase(e.boundary_type)}</td>
                  <td>{e.detection_source === 'both' ? 'Audio + words' : e.detection_source === 'vad' ? 'Audio only' : 'Words only'}</td>
                  <td>{hit ? <button type="button" className="link-btn" onClick={() => { selectFlaw(hit.flaw_id); navigate(analysisPath(analysis.id, 'flaws', hit.flaw_id)); }}>{hit.flaw_id}</button> : <span className="muted">-</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </ScrollRegion>
    </Panel>
  );
}

function MfccPanel({ analysis }: { analysis: LoadedAnalysis }) {
  const summary = analysis.result.features.mfcc_summary;
  const note = noteFor(analysis.result, 'mfcc_unavailable');
  return (
    <Panel eyebrow="Spectral shape of the voice" title="MFCC summary" actions={<Chip>Descriptive, not scored</Chip>}>
      {!summary ? <p className="muted">{note ?? 'The backend did not return an MFCC summary for this recording.'}</p> : (
        <>
          <ScrollRegion label="MFCC coefficients">
            <table className="table table--tight">
              <thead><tr><th>Coefficient</th><th className="r">Mean</th><th className="r">Std</th><th aria-hidden="true">Mean ± std (each row on its own scale)</th></tr></thead>
              <tbody>
                {summary.mean_13.map((mean, i) => {
                  const std = summary.std_13[i] ?? 0;
                  const reach = Math.max(Math.abs(mean) + std, 1e-9);
                  const pos = (v: number) => `${50 + (v / reach) * 48}%`;
                  return (
                    <tr key={i}>
                      <td className="num">c{i}</td>
                      <td className="num r">{fmtNum(mean, 1)}</td>
                      <td className="num r">{fmtNum(std, 1)}</td>
                      <td aria-hidden="true">
                        <span className="whisker">
                          <i className="whisker__zero" />
                          <i className="whisker__range" style={{ left: pos(mean - std), width: `${((2 * std) / reach) * 48}%` }} />
                          <i className="whisker__dot" style={{ left: pos(mean) }} />
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </ScrollRegion>
          <p className="panel__foot-note">Thirteen mel-frequency cepstral coefficients averaged over the recording. They describe the timbre of the voice for reference; no finding or score uses them yet.</p>
        </>
      )}
    </Panel>
  );
}

export function SignalsPage({ analysis }: { analysis: LoadedAnalysis }) {
  const { result } = analysis;
  const tc = useTimecode();
  const view = useStore(viewStore, (v) => v);
  const duration = recordingDuration(result);
  const bs = result.baseline_stats;
  const rate = result.features.speech_rate_timeline;
  const zoomed = span(view) < duration - 1e-6;
  const pitchNote = noteFor(result, 'pitch_not_scored');

  return (
    <div className="page">
      <PageHead
        eyebrow="Measurements"
        title="Signals"
        meta={<span>The measurements behind the findings, drawn against the baseline. The charts share one time window: zoom or pan any of them and the others follow.</span>}
        actions={(
          <>
            <span className="num muted signals__window">{tc.range(view.t0, view.t1)}</span>
            <Button size="sm" variant="secondary" icon="fit" disabled={!zoomed} onClick={() => setView(FULL(duration))}>Fit all</Button>
          </>
        )}
      />

      <SignalFigure
        no={1}
        analysis={analysis}
        lane="rate"
        height={190}
        title="Speech rate"
        note="One value per rolling window of words, drawn where its words are. Words per minute, with the baseline mean and spread behind it."
        facts={(
          <>
            <Fact label="Baseline mean">{fmtNum(bs.rate_wpm_mean, 1)} <span className="muted">words/min</span></Fact>
            <Fact label="Baseline spread">± {fmtNum(bs.rate_wpm_std, 1)} <span className="muted">words/min</span></Fact>
            <Fact label="Windows">{rate.times_s.length}</Fact>
          </>
        )}
        table={(
          <ScrollRegion label="Speech rate per window">
            <table className="table table--tight">
              <thead><tr><th>Window around</th><th className="r">Words/min</th></tr></thead>
              <tbody>{rate.times_s.map((t, i) => <tr key={i}><td className="num">{tc.at(t, 1)}</td><td className="num r">{fmtNum(rate.words_per_min[i], 1)}</td></tr>)}</tbody>
            </table>
          </ScrollRegion>
        )}
      />

      <SignalFigure
        no={2}
        analysis={analysis}
        lane="loudness"
        height={190}
        title="Loudness"
        note="Frame loudness in dBFS over time. Zoomed out, each pixel column shows its loudest frame, so dips are genuine quiet stretches. The recording is peak-normalised before analysis: levels describe relative loudness, not absolute volume."
        facts={(
          <>
            <Fact label="Baseline mean">{fmtLevel(bs.energy_db_mean, 1)} <span className="muted">dBFS</span></Fact>
            <Fact label="Baseline spread">± {fmtNum(bs.energy_db_std, 1)} <span className="muted">dB</span></Fact>
            <Fact label="Peak after normalising">{fmtLevel(result.audio.peak_dbfs, 1)} <span className="muted">dBFS</span></Fact>
          </>
        )}
      />

      <SignalFigure
        no={3}
        analysis={analysis}
        lane="pitch"
        height={210}
        title="Pitch (F0)"
        note="Fundamental frequency where the voice is voiced; unvoiced stretches have no estimate and are left empty. Shown for context: pitch does not enter the score yet."
        facts={(
          <>
            <Fact label="Baseline mean">{fmtNum(bs.f0_voiced_hz_mean, 1)} <span className="muted">Hz</span></Fact>
            <Fact label="Baseline spread">± {fmtNum(bs.f0_voiced_hz_std, 1)} <span className="muted">Hz</span></Fact>
            <Fact label="Baseline 5–95 %">{bs.f0_voiced_hz_p05 !== null && bs.f0_voiced_hz_p05 !== undefined && bs.f0_voiced_hz_p95 !== null && bs.f0_voiced_hz_p95 !== undefined ? `${fmtNum(bs.f0_voiced_hz_p05, 0)}–${fmtNum(bs.f0_voiced_hz_p95, 0)}` : '-'} <span className="muted">Hz</span></Fact>
          </>
        )}
      />
      {pitchNote ? <p className="signals__note"><Icon name="info" size={15} /><span>{pitchNote}</span></p> : null}

      <SignalFigure
        no={4}
        analysis={analysis}
        lane="pauses"
        height={84}
        title="Pauses"
        note="Each bar is one silence between words; taller means longer, darker means between sentences. Coloured bars were flagged as findings."
        facts={(
          <>
            <Fact label="Within a phrase">{fmtNum(bs.pause_within_phrase_mean_s, 2)} <span className="muted">s ± {fmtNum(bs.pause_within_phrase_std_s, 2)} in the baseline</span></Fact>
            <Fact label="Between sentences">{fmtNum(bs.pause_cross_sentence_mean_s, 2)} <span className="muted">s ± {bs.pause_cross_sentence_std_s === null || bs.pause_cross_sentence_std_s === undefined ? '-' : fmtNum(bs.pause_cross_sentence_std_s, 2)} in the baseline</span></Fact>
          </>
        )}
      />

      <div className="grid-split grid-split--even">
        <PauseTable analysis={analysis} />
        <MfccPanel analysis={analysis} />
      </div>
    </div>
  );
}
