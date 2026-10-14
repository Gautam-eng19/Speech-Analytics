import { useMemo } from 'react';
import { Icon } from '@/components/Icon';
import { EvidenceTable } from '@/components/EvidenceView';
import { SeverityBar } from '@/components/page';
import { Button, FlawTag } from '@/components/ui';
import { flawMeta } from '@/lib/flawMeta';
import { fmtLevel, fmtNum, titleCase } from '@/lib/format';
import { readAt } from '@/lib/lookup';
import { useTimecode } from '@/lib/settings';
import { useStore } from '@/lib/store';
import { analysisPath, navigate } from '@/app/router';
import { goToFlaw } from '@/state/actions';
import type { LoadedAnalysis } from '@/state/analysis';
import { clearRange, playerStore, usePlayhead } from '@/state/player';
import { hoverStore, selectFlaw } from '@/state/ui';
import type { Flaw } from '@/api/types';

/** The numbers under the pointer (or, when the pointer is away, under the playhead), read from the result. */
export function AtCursor({ analysis }: { analysis: LoadedAnalysis }) {
  const hover = useStore(hoverStore, (h) => h);
  const playhead = usePlayhead();
  const tc = useTimecode();
  const time = hover ?? playhead;
  const reading = useMemo(() => readAt(analysis.result, time), [analysis.result, time]);
  const bs = analysis.result.baseline_stats;

  return (
    <section className="side-block" aria-label="Values at the cursor">
      <header className="side-block__head">
        <span className="eyebrow">{hover !== null ? 'At the pointer' : 'At the playhead'}</span>
        <span className="num side-block__time">{tc.at(time, 2)}</span>
      </header>
      <dl className="readings">
        <div>
          <dt>Word</dt>
          <dd>{reading.word ? <><span className="readings__word">{reading.word.word}</span><span className="muted num"> conf {fmtNum(reading.word.confidence, 2)}</span></> : <span className="muted">between words</span>}</dd>
        </div>
        <div>
          <dt>Loudness</dt>
          <dd className="num">{reading.loudnessDb === null ? <span className="muted">outside analysed audio</span> : <>{fmtLevel(reading.loudnessDb, 1)} <span className="muted">dBFS</span> <span className="muted">· baseline {fmtLevel(bs.energy_db_mean, 1)}</span></>}</dd>
        </div>
        <div>
          <dt>Pitch</dt>
          <dd className="num">
            {reading.f0Hz === null ? <span className="muted">outside analysed audio</span> : reading.f0Hz === 'unvoiced' ? <span className="muted">unvoiced</span> : <>{fmtNum(reading.f0Hz, 0)} <span className="muted">Hz · baseline {fmtNum(bs.f0_voiced_hz_mean, 0)}</span></>}
          </dd>
        </div>
        <div>
          <dt>Rate</dt>
          <dd className="num">{reading.rate ? <>{fmtNum(reading.rate.wpm, 0)} <span className="muted">words/min · window at {tc.at(reading.rate.centre)}</span></> : <span className="muted">-</span>}</dd>
        </div>
        <div>
          <dt>Pause</dt>
          <dd className="num">{reading.pause ? <>{fmtNum(reading.pause.duration_s, 2)} <span className="muted">s · {titleCase(reading.pause.boundary_type)}</span></> : <span className="muted">not in a pause</span>}</dd>
        </div>
        <div>
          <dt>Findings</dt>
          <dd className="readings__flaws">{reading.flaws.length === 0 ? <span className="muted">none here</span> : reading.flaws.map((f) => <FlawTag key={f.flaw_id} type={f.type} />)}</dd>
        </div>
      </dl>
    </section>
  );
}

export function SelectedFinding({ analysis, flaw }: { analysis: LoadedAnalysis; flaw: Flaw | null }) {
  const tc = useTimecode();
  const hasAudio = useStore(playerStore, (s) => s.src !== null);
  const looping = useStore(playerStore, (s) => s.range?.loop ?? false);
  if (!flaw) {
    return (
      <section className="side-block side-block--hint" aria-label="Selected finding">
        <span className="eyebrow">Selected finding</span>
        <p>Click a coloured band in the Findings lane, or a finding on the strip above, to inspect its evidence here.</p>
      </section>
    );
  }
  const meta = flawMeta(flaw.type);
  return (
    <section className="side-block side-block--selected" aria-label="Selected finding" style={{ ['--c' as string]: `var(--f-${flaw.type})` }}>
      <header className="side-block__head">
        <span className="eyebrow">Selected finding</span>
        <button type="button" className="icon-btn icon-btn--small" aria-label="Clear selection" title="Clear selection (Esc)" onClick={() => selectFlaw(null)}><Icon name="x" size={14} /></button>
      </header>
      <div className="selected__title">
        <FlawTag type={flaw.type} />
        <span className="num muted">{flaw.flaw_id}</span>
      </div>
      <div className="selected__when num">{tc.range(flaw.start_s, flaw.end_s)} <span className="muted">· {fmtNum(flaw.duration_s, 1)} s</span></div>
      <div className="selected__sev">
        <SeverityBar value={flaw.severity} />
        <span className="muted">reliability <span className="num">{fmtNum(flaw.reliability, 2)}</span></span>
      </div>
      <EvidenceTable flaw={flaw} compact />
      <p className="selected__why">{flaw.explanation}</p>
      <p className="selected__tip"><Icon name="target" size={14} /> {flaw.recommendation}</p>
      <div className="selected__actions">
        {hasAudio ? <Button size="sm" variant="primary" icon="play" onClick={() => goToFlaw(flaw, { play: true })}>Play</Button> : null}
        {hasAudio ? <Button size="sm" variant="secondary" icon="loop" onClick={() => (looping ? clearRange() : goToFlaw(flaw, { play: true, loop: true }))}>{looping ? 'Stop loop' : 'Loop'}</Button> : null}
        <Button size="sm" variant="ghost" iconRight="arrow-right" onClick={() => navigate(analysisPath(analysis.id, 'flaws', flaw.flaw_id))}>Details</Button>
      </div>
      <span className="sr-only">{meta.definition}</span>
    </section>
  );
}

/** How to read the picture. */
export function Legend({ hasTruth }: { hasTruth: boolean }) {
  return (
    <section className="side-block" aria-label="Legend">
      <span className="eyebrow">How to read it</span>
      <ul className="legend">
        <li><i className="swatch swatch--band1" /><span>Shaded bands: the baseline’s mean ± 1 and ± 2 standard deviations. Dashed line: its mean.</span></li>
        <li><i className="swatch swatch--flag" /><span>Coloured bands: findings. The faint column through the lanes follows one finding from lane to lane.</span></li>
        <li><i className="swatch swatch--dot" /><span>Dots: one speech-rate value per rolling window, drawn at the middle of the words it covers.</span></li>
        <li><i className="swatch swatch--pause" /><span>Bars: pauses; taller is longer, darker is between sentences.</span></li>
        <li><i className="swatch swatch--trim" /><span>Hatching: leading or trailing silence trimmed before analysis.</span></li>
        {hasTruth ? <li><i className="swatch swatch--truth" /><span>Injected: where the synthetic sample was given a known flaw. Dashed means the analysis missed it.</span></li> : null}
      </ul>
    </section>
  );
}
