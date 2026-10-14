import { useMemo } from 'react';
import { TimelineStack } from '@/charts/TimelineStack';
import { EvidenceTable } from '@/components/EvidenceView';
import { Prose, SourceChip } from '@/components/page';
import { Button, FlawTag } from '@/components/ui';
import { Icon } from '@/components/Icon';
import { SCORE_DIMENSIONS } from '@/lib/flawMeta';
import { fmtDateTime, fmtDuration, fmtLevel, fmtNum, plural, titleCase } from '@/lib/format';
import { NOTE_CATEGORY_LABEL, noteMeta } from '@/lib/notesMeta';
import { analysedSpan, flawsByTime, recordingDuration } from '@/lib/result';
import { useTimecode } from '@/lib/settings';
import { FULL } from '@/lib/time';
import { analysisPath, navigate } from '@/app/router';
import type { LoadedAnalysis } from '@/state/analysis';

/**
 * The analysis as a document: a summary, the figure, every finding with its evidence, the baseline it was compared with and the
 * notes that limit it. It prints on A4 (the browser's "Save as PDF" makes the file) and contains nothing the other pages do not.
 */
export function ReportPage({ analysis }: { analysis: LoadedAnalysis }) {
  const { result } = analysis;
  const tc = useTimecode();
  const duration = recordingDuration(result);
  const span = analysedSpan(result);
  const view = useMemo(() => FULL(duration), [duration]);
  const flaws = useMemo(() => flawsByTime(result.flaws), [result.flaws]);
  const printedOn = useMemo(() => fmtDateTime(Date.now()), []);
  const bs = result.baseline_stats;

  return (
    <div className="page page--report">
      <div className="report-bar no-print">
        <div>
          <div className="eyebrow">Printable report</div>
          <p>Laid out for A4. Use “Save as PDF” in the print dialog to keep a copy.</p>
        </div>
        <div className="report-bar__actions">
          <Button variant="ghost" icon="arrow-left" onClick={() => navigate(analysisPath(analysis.id, 'overview'))}>Overview</Button>
          <Button variant="primary" icon="printer" onClick={() => window.print()}>Print or save as PDF</Button>
        </div>
      </div>

      <article className="report paper" aria-label="Delivery analysis report">
        <header className="report__head">
          <div className="eyebrow">VAANI · Delivery report</div>
          <h2 className="report__title">{analysis.title}</h2>
          <p className="report__meta">
            {fmtDuration(duration)} recording · analysed {tc.range(span.start, span.end)} · baseline <span className="num">{result.baseline.baseline_id}</span> · printed {printedOn}
          </p>
          {analysis.source === 'sample' ? <p className="report__sample"><SourceChip source="sample" /> A synthetic voice with deliberately injected flaws; it demonstrates the report and is not a person’s speech.</p> : null}
        </header>

        <section className="report__summary">
          <div className="report__score">
            <div className="eyebrow">Deviation score</div>
            <div className="report__score-num">{fmtNum(result.scores.composite_score, 1)}<span className="num"> / 100</span></div>
            <p>100 means no deviation from the baseline was detected. It is not a grade of speech quality or content.</p>
          </div>
          <div>
            <div className="eyebrow">Summary</div>
            <p className="report__lead">{result.overall_summary ?? 'No summary was returned.'}</p>
          </div>
        </section>

        <section className="report__figure" aria-label="Figure">
          <h3>Figure 1 · Delivery against the baseline</h3>
          <TimelineStack
            analysis={analysis}
            lanes={['flaws', 'rate', 'loudness', 'pauses']}
            view={view}
            compact
            selected={null}
            onSelect={() => undefined}
            showTruth={false}
            label="Delivery against the baseline"
          />
          <p className="report__caption">Shaded bands: baseline mean ± 1 and 2 standard deviations. Coloured bands: findings. Hatching: silence trimmed before analysis.</p>
        </section>

        <section>
          <h3>Findings ({flaws.length})</h3>
          {flaws.length === 0 ? <p>No stretch of the recording crossed a detection rule against the baseline.</p> : (
            <ol className="report__findings">
              {flaws.map((f, i) => (
                <li key={f.flaw_id} className="report__finding">
                  <div className="report__finding-head">
                    <span className="num report__finding-no">{i + 1}</span>
                    <FlawTag type={f.type} />
                    <span className="num">{tc.range(f.start_s, f.end_s)}</span>
                    <span className="muted num">{fmtNum(f.duration_s, 1)} s</span>
                    <span className="report__spacer" />
                    <span className="num muted">severity {fmtNum(f.severity, 2)} · reliability {fmtNum(f.reliability, 2)}</span>
                  </div>
                  <EvidenceTable flaw={f} compact />
                  <Prose text={f.explanation} />
                  <p className="report__reco"><Icon name="target" size={14} /> <span>{f.recommendation}</span></p>
                  {f.warnings && f.warnings.length > 0 ? <p className="report__warn">{f.warnings.join(' ')}</p> : null}
                </li>
              ))}
            </ol>
          )}
        </section>

        <section className="report__two">
          <div>
            <h3>Score by dimension</h3>
            <table className="table table--tight">
              <thead><tr><th>Dimension</th><th className="r">Score</th><th className="r">Weight</th><th className="r">Findings</th></tr></thead>
              <tbody>
                {SCORE_DIMENSIONS.map((d) => {
                  const entry = result.scores.feature_scores[d.key];
                  return entry ? (
                    <tr key={d.key}><td>{d.label}</td><td className="num r">{fmtNum(entry.score, 1)}</td><td className="num r">{fmtNum(entry.weight * 100, 0)} %</td><td className="num r">{entry.flaw_count}</td></tr>
                  ) : (
                    <tr key={d.key}><td>{d.label}</td><td className="r muted" colSpan={3}>not scored</td></tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div>
            <h3>Baseline statistics</h3>
            <table className="table table--tight">
              <tbody>
                <tr><td>Speech rate</td><td className="num r">{fmtNum(bs.rate_wpm_mean, 1)} ± {fmtNum(bs.rate_wpm_std, 1)} words/min</td></tr>
                <tr><td>Loudness</td><td className="num r">{fmtLevel(bs.energy_db_mean, 1)} ± {fmtNum(bs.energy_db_std, 1)} dBFS</td></tr>
                <tr><td>Pause in a phrase</td><td className="num r">{fmtNum(bs.pause_within_phrase_mean_s, 2)} ± {fmtNum(bs.pause_within_phrase_std_s, 2)} s</td></tr>
                <tr><td>Pause between sentences</td><td className="num r">{fmtNum(bs.pause_cross_sentence_mean_s, 2)} ± {bs.pause_cross_sentence_std_s === null || bs.pause_cross_sentence_std_s === undefined ? '-' : fmtNum(bs.pause_cross_sentence_std_s, 2)} s</td></tr>
                <tr><td>Pitch (context)</td><td className="num r">{fmtNum(bs.f0_voiced_hz_mean, 1)} ± {fmtNum(bs.f0_voiced_hz_std, 1)} Hz</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <h3>Notes and limitations ({plural((result.notes ?? []).length, 'note')})</h3>
          <ul className="report__notes">
            {(result.notes ?? []).map((n) => {
              const meta = noteMeta(n.code);
              return <li key={n.code}><strong>{meta.title}</strong> <span className="muted">({NOTE_CATEGORY_LABEL[meta.category]})</span><br />{n.message}</li>;
            })}
          </ul>
        </section>

        <footer className="report__foot">
          <h3>Provenance</h3>
          <dl className="report__prov num">
            <div><dt>Analysis id</dt><dd>{result.analysis_id}</dd></div>
            <div><dt>Recording SHA-256</dt><dd>{result.audio.sha256}</dd></div>
            <div><dt>Baseline SHA-256</dt><dd>{result.baseline.sha256}</dd></div>
            <div><dt>Configuration</dt><dd>v{result.config_version}{result.config_fingerprint ? ` · ${result.config_fingerprint}` : ''}</dd></div>
            <div><dt>Versions</dt><dd>pipeline {result.pipeline_version} · scoring {result.scores.scoring_version} · API {result.api_contract_version}</dd></div>
            <div><dt>Alignment</dt><dd>{titleCase(result.alignment_method)} · transcript {result.processing_meta.transcript_source}</dd></div>
          </dl>
          <p className="report__caption">This report compares delivery with a baseline recording. It does not assess the content or quality of the speech. Thresholds and weights are initial, uncalibrated values.</p>
        </footer>
      </article>
    </div>
  );
}
