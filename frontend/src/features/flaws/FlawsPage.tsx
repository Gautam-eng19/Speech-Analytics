import { useEffect, useMemo } from 'react';
import type { DetectionRule, Flaw } from '@/api/types';
import { laneHeights, type LaneKey } from '@/charts/geometry';
import { TimelineStack } from '@/charts/TimelineStack';
import { EvidenceGauge, EvidenceTable } from '@/components/EvidenceView';
import { Icon } from '@/components/Icon';
import { Figure, PageHead, Prose, SeverityBar } from '@/components/page';
import { Button, Chip, CopyButton, EmptyState, FlawTag, IconButton, Panel, Segmented, ToggleChip } from '@/components/ui';
import { evidenceHeadline } from '@/lib/evidence';
import { FLAW_ORDER, flawMeta } from '@/lib/flawMeta';
import { fmtNum, plural } from '@/lib/format';
import { dimensionOf, flawsBySeverity, flawsByTime, recordingDuration } from '@/lib/result';
import { useTimecode } from '@/lib/settings';
import { useStore } from '@/lib/store';
import { windowAround } from '@/lib/time';
import { useMedia } from '@/lib/useMedia';
import { analysisPath, navigate } from '@/app/router';
import { goToFlaw } from '@/state/actions';
import type { LoadedAnalysis } from '@/state/analysis';
import { clearRange, playerStore, seek } from '@/state/player';
import { flawsFilterStore, selectFlaw, setFlawsFilter } from '@/state/ui';

const RULE_FEATURE: Record<string, string> = {
  rate_z: 'speech-rate z-score',
  pause_z: 'pause-length z-score',
  energy_z: 'loudness z-score',
};

/** The detection rule in words. Feature, direction, threshold and minimum duration are the backend's. */
function ruleSentence(rule: DetectionRule): string {
  const feature = RULE_FEATURE[rule.feature] ?? rule.feature.replace(/_/g, ' ');
  const threshold = fmtNum(rule.threshold_z, 1);
  const where = rule.direction === 'above' ? `above ${threshold}` : `below ${threshold}`;
  return rule.min_duration_s > 0
    ? `Flagged when the ${feature} stayed ${where} for at least ${fmtNum(rule.min_duration_s, 1)} s.`
    : `Flagged when the ${feature} was ${where}; one event is enough, there is no minimum duration.`;
}

/** The lane that shows what a finding measured, for the close-up. */
function laneFor(flaw: Flaw): LaneKey {
  switch (dimensionOf(flaw.type)) {
    case 'speech_rate': return 'rate';
    case 'pauses': return 'pauses';
    case 'energy': return 'loudness';
    default: return 'pitch';
  }
}

function useVisibleFlaws(flaws: readonly Flaw[]): Flaw[] {
  const filter = useStore(flawsFilterStore, (f) => f);
  return useMemo(() => {
    const kept = filter.types.length === 0 ? [...flaws] : flaws.filter((f) => filter.types.includes(f.type));
    return filter.sort === 'severity' ? flawsBySeverity(kept) : flawsByTime(kept);
  }, [flaws, filter]);
}

// ---- list ----------------------------------------------------------------------------------------------------------------------
function FlawList({ analysis, flaws, activeId, order }: { analysis: LoadedAnalysis; flaws: readonly Flaw[]; activeId: string | null; order: Map<string, number> }) {
  const tc = useTimecode();
  const filter = useStore(flawsFilterStore, (f) => f);
  const all = analysis.result.flaws;
  const present = FLAW_ORDER.filter((type) => all.some((f) => f.type === type));
  const toggle = (type: string, on: boolean) => {
    const types = on ? [...filter.types, type] : filter.types.filter((t) => t !== type);
    setFlawsFilter({ types });
  };
  return (
    <div className="flaws__list">
      <div className="flaws__filters">
        <div className="flaws__chips" role="group" aria-label="Filter by finding type">
          <ToggleChip on={filter.types.length === 0} onChange={() => setFlawsFilter({ types: [] })}>All {all.length}</ToggleChip>
          {present.map((type) => (
            <ToggleChip key={type} on={filter.types.includes(type)} onChange={(on) => toggle(type, on)} icon={flawMeta(type).icon}>
              {flawMeta(type).label} {all.filter((f) => f.type === type).length}
            </ToggleChip>
          ))}
        </div>
        <Segmented
          label="Sort findings"
          size="sm"
          value={filter.sort}
          onChange={(sort) => setFlawsFilter({ sort })}
          options={[{ value: 'time', label: 'By time' }, { value: 'severity', label: 'By severity' }]}
        />
      </div>
      {flaws.length === 0 ? <p className="flaws__none">No finding matches this filter.</p> : (
        <ul className="flaw-list" role="listbox" aria-label="Findings">
          {flaws.map((f) => (
            <li key={f.flaw_id} role="presentation">
              <button
                type="button"
                role="option"
                aria-selected={f.flaw_id === activeId}
                className={`flaw-item ${f.flaw_id === activeId ? 'is-active' : ''}`}
                style={{ ['--c' as string]: `var(--f-${f.type})` }}
                onClick={() => { selectFlaw(f.flaw_id); navigate(analysisPath(analysis.id, 'flaws', f.flaw_id)); }}
              >
                <span className="flaw-item__no num">{String(order.get(f.flaw_id) ?? 0).padStart(2, '0')}</span>
                <span className="flaw-item__body">
                  <span className="flaw-item__line"><FlawTag type={f.type} /></span>
                  <span className="flaw-item__when num">{tc.range(f.start_s, f.end_s)}<span className="muted"> · {fmtNum(f.duration_s, 1)} s</span></span>
                  <span className="flaw-item__evidence num">{evidenceHeadline(f)}</span>
                </span>
                <SeverityBar value={f.severity} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---- detail ------------------------------------------------------------------------------------------------------------------------
function FlawDetail({ analysis, flaw, position, total, onStep }: { analysis: LoadedAnalysis; flaw: Flaw; position: number; total: number; onStep: (direction: 1 | -1) => void }) {
  const tc = useTimecode();
  const hasAudio = useStore(playerStore, (s) => s.src !== null);
  const looping = useStore(playerStore, (s) => s.range?.loop ?? false);
  const meta = flawMeta(flaw.type);
  const duration = recordingDuration(analysis.result);
  const view = useMemo(() => windowAround(flaw.start_s, flaw.end_s, duration, 0.8), [flaw, duration]);
  const lanes = useMemo<LaneKey[]>(() => ['flaws', 'words', laneFor(flaw)], [flaw]);
  const base = laneHeights(false);

  return (
    <div className="flaw-detail" style={{ ['--c' as string]: `var(--f-${flaw.type})` }}>
      <header className="flaw-detail__head">
        <div className="flaw-detail__titles">
          <div className="eyebrow">Finding {position} of {total} <span aria-hidden="true">·</span> <span className="num">{flaw.flaw_id}</span></div>
          <div className="flaw-detail__title">
            <FlawTag type={flaw.type} />
            <span className="flaw-detail__when num">{tc.range(flaw.start_s, flaw.end_s)}</span>
            <span className="muted num">{fmtNum(flaw.duration_s, 1)} s</span>
          </div>
        </div>
        <div className="flaw-detail__nav">
          <IconButton icon="chevron-up" label="Previous finding (k)" onClick={() => onStep(-1)} disabled={position <= 1} />
          <IconButton icon="chevron-down" label="Next finding (j)" onClick={() => onStep(1)} disabled={position >= total} />
        </div>
      </header>

      <div className="flaw-detail__metrics">
        <div><span className="eyebrow">Severity</span><SeverityBar value={flaw.severity} /></div>
        <div><span className="eyebrow">Reliability</span><SeverityBar value={flaw.reliability} label="Reliability" /></div>
        <div className="flaw-detail__chips">
          {flaw.low_confidence ? <Chip tone="warn" icon="alert-triangle">Low confidence</Chip> : null}
          <Chip icon="shield-check">{flaw.explanation_method === 'template' ? 'Template explanation' : `Explanation: ${flaw.explanation_method}`}</Chip>
        </div>
      </div>

      <Figure title="The moment" note="The finding with its words and the signal it was measured on, from the same recording.">
        <TimelineStack
          analysis={analysis}
          lanes={lanes}
          heights={{ flaws: base.flaws, words: base.words, [laneFor(flaw)]: 104 }}
          view={view}
          selected={flaw}
          onSelect={() => undefined}
          onPlotClick={(t) => { if (playerStore.get().src) seek(t); }}
          showTruth={false}
          label={`Close-up of ${meta.label} between ${fmtNum(flaw.start_s, 1)} and ${fmtNum(flaw.end_s, 1)} seconds`}
        />
      </Figure>

      <div className="grid-2">
        <Panel eyebrow="Measured" title="Evidence">
          <EvidenceGauge flaw={flaw} />
          <hr className="hr" />
          <EvidenceTable flaw={flaw} />
        </Panel>
        <div className="flaw-detail__text">
          <Panel eyebrow="Why this is a delivery flaw" title="Explanation">
            <Prose text={flaw.explanation} />
          </Panel>
          <Panel eyebrow="What to try" title="Recommendation">
            <Prose text={flaw.recommendation} />
          </Panel>
        </div>
      </div>

      <div className="grid-2">
        <Panel eyebrow="Why it was flagged" title="Detection rule">
          {flaw.rule ? (
            <>
              <p className="prose">{ruleSentence(flaw.rule)}</p>
              <p className="prose prose--small">A z-score counts how many baseline standard deviations a value is from the baseline mean, so the rule compares this delivery with the baseline recording, not with a fixed target. {meta.measured}</p>
            </>
          ) : <p className="prose">The backend did not attach a rule to this finding.</p>}
          {flaw.warnings && flaw.warnings.length > 0 ? (
            <ul className="warnings">
              {flaw.warnings.map((w) => <li key={w}><Icon name="alert-triangle" size={15} /><span>{w}</span></li>)}
            </ul>
          ) : null}
        </Panel>
        <Panel eyebrow={`${plural(flaw.affected_words?.length ?? 0, 'word')} inside`} title="Affected words" actions={<Button size="sm" variant="ghost" iconRight="arrow-right" onClick={() => navigate(analysisPath(analysis.id, 'transcript'))}>Transcript</Button>}>
          {flaw.affected_words && flaw.affected_words.length > 0 ? (
            <p className="affected">{flaw.affected_words.join(' ')}</p>
          ) : <p className="muted">No words were attached to this finding.</p>}
        </Panel>
      </div>

      <div className="flaw-detail__actions">
        {hasAudio ? <Button variant="primary" icon="play" onClick={() => goToFlaw(flaw, { play: true })}>Play this stretch</Button> : null}
        {hasAudio ? <Button icon="loop" onClick={() => (looping ? clearRange() : goToFlaw(flaw, { play: true, loop: true }))}>{looping ? 'Stop loop' : 'Loop'}</Button> : null}
        <Button icon="gantt" onClick={() => { goToFlaw(flaw); navigate(analysisPath(analysis.id, 'timeline')); }}>Show on timeline</Button>
        <span className="flaw-detail__spacer" />
        <CopyButton text={JSON.stringify(flaw, null, 2)} label="Copy this finding as JSON" what="Finding" />
        <span className="muted">Copy as JSON</span>
      </div>
    </div>
  );
}

// ---- page ------------------------------------------------------------------------------------------------------------------------
export function FlawsPage({ analysis, flawId }: { analysis: LoadedAnalysis; flawId?: string | null }) {
  const { result } = analysis;
  const wide = useMedia('(min-width: 1101px)');
  const visible = useVisibleFlaws(result.flaws);
  const order = useMemo(() => new Map(flawsByTime(result.flaws).map((f, i) => [f.flaw_id, i + 1] as const)), [result.flaws]);
  const requested = flawId ? result.flaws.find((f) => f.flaw_id === flawId) ?? null : null;
  const active = requested ?? (wide ? visible[0] ?? null : null);
  const index = active ? visible.findIndex((f) => f.flaw_id === active.flaw_id) : -1;

  // Keep the shared selection (ribbon, timeline) in step with the page.
  useEffect(() => { if (active) selectFlaw(active.flaw_id); }, [active?.flaw_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const step = (direction: 1 | -1) => {
    const next = visible[(index < 0 ? (direction === 1 ? -1 : visible.length) : index) + direction];
    if (next) navigate(analysisPath(analysis.id, 'flaws', next.flaw_id));
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable)) return;
      if (e.key === 'j') { e.preventDefault(); step(1); }
      else if (e.key === 'k') { e.preventDefault(); step(-1); }
      else if (e.key === 'Enter' && active && !(target?.closest('button, a'))) { e.preventDefault(); goToFlaw(active, { play: true }); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  if (result.flaws.length === 0) {
    return (
      <div className="page">
        <PageHead eyebrow="Findings" title="No findings" />
        <EmptyState icon="check" title="Nothing crossed a detection rule" action={<Button variant="primary" onClick={() => navigate(analysisPath(analysis.id, 'overview'))}>Back to the overview</Button>}>
          No stretch of this recording deviated from the baseline enough to be flagged. The notes on the overview say which checks ran and which could not.
        </EmptyState>
      </div>
    );
  }

  const showList = wide || !active;
  const showDetail = wide || !!active;

  return (
    <div className="page page--flaws">
      <PageHead
        eyebrow="Findings"
        title={`${plural(result.flaws.length, 'finding')}`}
        meta={<span>Each one ties a time interval to measured evidence, a reason and a recommendation.</span>}
      />
      <div className="flaws">
        {showList ? <FlawList analysis={analysis} flaws={visible} activeId={active?.flaw_id ?? null} order={order} /> : null}
        {showDetail && active ? (
          <div className="flaws__detail">
            {!wide ? <Button size="sm" variant="ghost" icon="arrow-left" onClick={() => navigate(analysisPath(analysis.id, 'flaws'))}>All findings</Button> : null}
            <FlawDetail analysis={analysis} flaw={active} position={Math.max(1, index + 1)} total={visible.length} onStep={step} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

