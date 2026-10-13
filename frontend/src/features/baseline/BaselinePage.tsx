import { useEffect, useState } from 'react';
import type { BaselineSummary, SampleIndex } from '@/api/types';
import { Icon, type IconName } from '@/components/Icon';
import { Fact, HashValue, PageHead, Prose } from '@/components/page';
import { Chip, FlawTag, Panel, ScrollRegion } from '@/components/ui';
import { FLAW_META, FLAW_ORDER } from '@/lib/flawMeta';
import { fmtLevel, fmtNum, plural } from '@/lib/format';
import { loadSamples, type LoadedAnalysis } from '@/state/analysis';
import { refreshCatalog, useCatalog } from '@/state/connection';

/** The canonical pipeline (AGENTS.md section 2), with what each step contributes. Static documentation of the method. */
const PIPELINE: { icon: IconName; name: string; what: string }[] = [
  { icon: 'file-audio', name: 'Preprocess', what: 'Decode, resample to 16 kHz mono, trim leading and trailing silence, normalise the peak.' },
  { icon: 'text', name: 'Transcribe and align', what: 'Speech recognition, then forced alignment, give every word a start and end time.' },
  { icon: 'chart', name: 'Extract features', what: 'Pitch, loudness, speech rate in rolling windows, pauses, MFCCs: one implementation each, deterministic.' },
  { icon: 'ruler', name: 'Normalise to the baseline', what: 'Each value becomes a z-score: how many baseline standard deviations it lies from the baseline mean.' },
  { icon: 'flag', name: 'Detect and ground', what: 'A rule per finding type flags stretches that stay beyond its threshold, with start and end times.' },
  { icon: 'gauge', name: 'Severity and score', what: 'Each finding gets a severity and a reliability; the score loses points per finding, per dimension, then combines them.' },
  { icon: 'book', name: 'Explain', what: 'Templates turn the measured evidence into a sentence and a recommendation. No number is written by a language model.' },
];

const LIMITS = [
  'It measures how delivery differs from a baseline recording of the same passage. It does not judge what was said, the writing, or the argument.',
  'Thresholds and score weights are starting values that have not been calibrated on recorded data. Treat findings as indicative.',
  'Speech rate is detected over rolling windows and the finding is then narrowed to the words that were faster or slower, so its start and end can still be off by a word or two. A silence longer than one second counts as one second, so a long pause is reported as a pause and not also as slow speech.',
  'Pitch is shown for context. No pitch finding is detected yet because the baseline has no statistic of pitch variation within a window.',
  'Loudness is relative: each recording is scaled so that its typical speech level is the same as the baseline’s, so it describes shape, not absolute volume.',
];

function statRows(baseline: LoadedAnalysis['result']['baseline_stats']) {
  const sd = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '-' : fmtNum(v, d));
  return [
    { label: 'Speech rate', value: `${fmtNum(baseline.rate_wpm_mean, 1)} ± ${fmtNum(baseline.rate_wpm_std, 1)}`, unit: 'words/min', used: 'Too fast, too slow' },
    { label: 'Loudness', value: `${fmtLevel(baseline.energy_db_mean, 1)} ± ${fmtNum(baseline.energy_db_std, 1)}`, unit: 'dBFS', used: 'Low energy, high energy' },
    { label: 'Pause inside a phrase', value: `${fmtNum(baseline.pause_within_phrase_mean_s, 2)} ± ${fmtNum(baseline.pause_within_phrase_std_s, 2)}`, unit: 's', used: 'Excessive pause' },
    { label: 'Pause between sentences', value: `${fmtNum(baseline.pause_cross_sentence_mean_s, 2)} ± ${sd(baseline.pause_cross_sentence_std_s, 2)}`, unit: 's', used: 'Excessive pause' },
    { label: 'Pitch (voiced)', value: `${fmtNum(baseline.f0_voiced_hz_mean, 1)} ± ${fmtNum(baseline.f0_voiced_hz_std, 1)}`, unit: 'Hz', used: 'Context only', extra: baseline.f0_voiced_hz_p05 !== null && baseline.f0_voiced_hz_p05 !== undefined && baseline.f0_voiced_hz_p95 !== null && baseline.f0_voiced_hz_p95 !== undefined ? `5–95 %: ${fmtNum(baseline.f0_voiced_hz_p05, 0)}–${fmtNum(baseline.f0_voiced_hz_p95, 0)} Hz` : undefined },
    { label: 'High-frequency ratio', value: baseline.hf_ratio_mean === null || baseline.hf_ratio_mean === undefined ? 'not available' : `${fmtNum(baseline.hf_ratio_mean, 3)} ± ${sd(baseline.hf_ratio_std, 3)}`, unit: '', used: 'Reduced clarity (planned)' },
  ];
}

export function BaselinePage({ analysis }: { analysis: LoadedAnalysis }) {
  const { result } = analysis;
  const catalog = useCatalog();
  const [samples, setSamples] = useState<SampleIndex | null>(null);

  useEffect(() => {
    void refreshCatalog();
    let cancelled = false;
    if (analysis.sample) loadSamples().then((s) => !cancelled && setSamples(s)).catch(() => undefined);
    return () => { cancelled = true; };
  }, [analysis.sample]);

  const summary: BaselineSummary | undefined = catalog.data?.baselines?.find((b) => b.baseline_id === result.baseline.baseline_id);
  const passage = summary?.passage_text ? { title: summary.passage_title ?? result.baseline.passage_id, text: summary.passage_text, words: summary.passage_word_count ?? null }
    : samples && samples.passage.passage_id === result.baseline.passage_id ? { title: samples.passage.title, text: samples.passage.text, words: samples.passage.word_count } : null;
  const takes = summary?.n_baseline_recordings ?? (samples && samples.baseline.baseline_id === result.baseline.baseline_id ? samples.baseline.takes : null);
  const rows = statRows(result.baseline_stats);

  return (
    <div className="page">
      <PageHead
        eyebrow="Method"
        title="Baseline and method"
        meta={<span>What this analysis was compared with, how a finding is made, and what the numbers can and cannot tell you.</span>}
      />

      <div className="grid-split">
        <Panel eyebrow="The comparison" title="Baseline statistics" flush>
          <ScrollRegion label="Baseline statistics">
            <table className="table">
              <thead><tr><th>Measure</th><th className="r">Mean ± std</th><th>Unit</th><th>Used for</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.label}>
                    <td>{r.label}{r.extra ? <div className="muted table__sub">{r.extra}</div> : null}</td>
                    <td className="num r">{r.value}</td>
                    <td className="muted">{r.unit}</td>
                    <td>{r.used}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        </Panel>
        <Panel eyebrow="Identity" title="This baseline">
          <dl className="facts">
            <Fact label="Baseline id" mono>{result.baseline.baseline_id}</Fact>
            <Fact label="Passage" mono>{result.baseline.passage_id}</Fact>
            <Fact label="Dataset">{result.baseline.dataset_version}</Fact>
            <Fact label="Fingerprint"><HashValue value={result.baseline.sha256} length={13} what="baseline hash" /></Fact>
            <Fact label="Recordings">{takes === null ? <span className="muted">unknown (API offline)</span> : takes}</Fact>
            {summary ? <Fact label="Rate windows">{summary.n_rate_windows}</Fact> : null}
            {summary ? <Fact label="Pauses (phrase)">{summary.n_pauses_within_phrase}</Fact> : null}
          </dl>
          {summary && (summary.thin_rate_statistics || summary.thin_pause_statistics) ? (
            <p className="baseline__warn"><Chip tone="warn" icon="alert-triangle">Thin statistics</Chip><span>{[summary.thin_rate_statistics ? 'speech rate' : null, summary.thin_pause_statistics ? 'pauses' : null].filter(Boolean).join(' and ')} rest on few observations, so z-scores against this baseline are less certain.</span></p>
          ) : null}
          <p className="panel__foot-note">A baseline is the effective delivery of the same content, not a universal human average. Its statistics are fixed by its fingerprint, so a result can always be traced back to the exact baseline used.</p>
        </Panel>
      </div>

      {passage ? (
        <Panel eyebrow={`Passage · ${passage.words ? plural(passage.words, 'word') : 'text'}`} title={passage.title}>
          <p className="passage">{passage.text}</p>
        </Panel>
      ) : null}

      <section aria-label="How a finding is made">
        <div className="section-head"><span className="eyebrow">Method</span><h3>How a finding is made</h3></div>
        <ol className="pipeline">
          {PIPELINE.map((step, i) => (
            <li key={step.name} className="pipeline__step">
              <div className="pipeline__icon"><Icon name={step.icon} size={18} /></div>
              <div className="pipeline__no num">{String(i + 1).padStart(2, '0')}</div>
              <div className="pipeline__name">{step.name}</div>
              <p className="pipeline__what">{step.what}</p>
            </li>
          ))}
        </ol>
        <p className="pipeline__foot">Same recording, baseline and configuration always give the same numbers: every step above is deterministic.</p>
      </section>

      <Panel eyebrow="Vocabulary" title="Finding types" flush>
        <ScrollRegion label="Finding types">
          <table className="table">
            <thead><tr><th>Type</th><th>What it means</th><th>Measured as</th><th>Status</th></tr></thead>
            <tbody>
              {FLAW_ORDER.map((type) => {
                const meta = FLAW_META[type];
                return (
                  <tr key={type}>
                    <td><FlawTag type={type} /></td>
                    <td className="table__wide">{meta.definition}</td>
                    <td className="table__wide muted">{meta.measured}</td>
                    <td>{meta.available ? <Chip tone="good" icon="check">Detected</Chip> : <Chip icon="clock">Not yet</Chip>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </ScrollRegion>
      </Panel>

      <Panel eyebrow="Honest scope" title="What to keep in mind">
        <ul className="limits">
          {LIMITS.map((text) => <li key={text}><Icon name="info" size={16} /><Prose text={text} /></li>)}
        </ul>
      </Panel>
    </div>
  );
}
