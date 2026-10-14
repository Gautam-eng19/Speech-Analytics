import type { MouseEvent, ReactNode } from 'react';
import { analysisPath, navigate } from '@/app/router';
import { Icon, type IconName } from '@/components/Icon';
import { Prose } from '@/components/page';
import { Button, FlawTag } from '@/components/ui';
import { evidenceHeadline, evidenceRows } from '@/lib/evidence';
import { FLAW_META, FLAW_ORDER, flawMeta } from '@/lib/flawMeta';
import { fmtClock } from '@/lib/format';
import { flawsBySeverity } from '@/lib/result';
import { openSample } from '@/state/analysis';
import { HeroInstrument } from './HeroInstrument';
import { goToSection } from './LandingNav';
import { useDemoSample, type DemoState } from './useDemoSample';

/**
 * The landing page. It is the existing home route (#/): a hero with the live instrument, three short sections about the method,
 * the evidence and the journey, then the working analysis flow itself (passed in as children), then a footer.
 * Nothing here states a figure of its own: every number on the page is read from the demo sample's real analysis result.
 */

function Hero({ demo }: { demo: DemoState }) {
  const sample = demo.sample;
  const openDemo = async () => {
    if (!sample) { goToSection('method'); return; }
    if (await openSample(sample.entry.id)) navigate(analysisPath(sample.entry.analysis_id, 'timeline'));
  };
  return (
    <section className="lhero" aria-labelledby="landing-title">
      <div className="lhero__top">
        <h1 id="landing-title" className="lhero__title">
          <span className="lhero__line">Hear the difference.</span>
          <span className="lhero__line lhero__line--2">Understand the why.</span>
        </h1>
        <div className="lhero__side">
          <p className="lhero__lede">
            VAANI compares a spoken delivery with an effective reading of the same passage, then shows where it drifted: which measurable signal changed, by how much, and exactly when.
          </p>
          <div className="lhero__cta">
            <Button variant="primary" size="lg" iconRight="arrow-right" onClick={() => goToSection('start')}>Analyse a recording</Button>
            <Button variant="secondary" size="lg" onClick={() => void openDemo()}>{sample ? 'Explore a demo analysis' : 'See how it works'}</Button>
          </div>
        </div>
      </div>
      <HeroInstrument sample={sample} loading={demo.status === 'loading'} />
    </section>
  );
}

function SectionHead({ id, title, lede }: { id: string; title: ReactNode; lede?: ReactNode }) {
  return (
    <header className="lsec__head">
      <h2 id={`${id}-title`} className="lsec__title" tabIndex={-1} data-section-heading>{title}</h2>
      {lede ? <p className="lsec__lede">{lede}</p> : null}
    </header>
  );
}

function Method() {
  const types = FLAW_ORDER.map((t) => FLAW_META[t]).filter((m) => m.available);
  return (
    <section id="method" className="lsec lsec--split" aria-labelledby="method-title">
      <div className="lsec__main">
        <SectionHead
          id="method"
          title="Compared with the same words, delivered well."
          lede="A baseline is not an average speaker. It is an effective reading of the same passage. VAANI measures how that reading paced each word, how loud it was and where it paused, then measures your recording against those values."
        />
        <p className="lsec__body">
          Pitch is judged by how far the voice moves around its own median, and loudness after removing the recording&rsquo;s overall level, so a deeper voice or a quieter microphone is not mistaken for a flaw.
          Everything measured is deterministic: the same recording, baseline and configuration always give the same numbers.
        </p>
        <p className="lsec__fine">Measured: pitch (F0), loudness, speech rate, pauses and MFCCs. VAANI judges how something is said, not what is said.</p>
      </div>
      <div className="lsec__aside">
        <h3 className="lsec__minor">What it listens for</h3>
        <ul className="vocab">
          {types.map((m) => (
            <li key={m.type} className="vocab__item">
              <span className="vocab__icon"><Icon name={m.icon} size={17} /></span>
              <div><strong>{m.label}</strong><p>{m.definition}</p></div>
            </li>
          ))}
        </ul>
        <p className="lsec__fine">Planned, not detected yet: pitch instability and reduced clarity.</p>
      </div>
    </section>
  );
}

function Evidence({ demo }: { demo: DemoState }) {
  const sample = demo.sample;
  const flaws = sample ? [...sample.result.flaws].sort((a, b) => a.start_s - b.start_s) : [];
  const featured = sample ? flawsBySeverity(sample.result.flaws)[0] ?? null : null;
  const open = async (flawId: string) => {
    if (!sample) return;
    if (await openSample(sample.entry.id)) navigate(analysisPath(sample.entry.analysis_id, 'flaws', flawId));
  };
  return (
    <section id="evidence" className="lsec" aria-labelledby="evidence-title">
      <SectionHead
        id="evidence"
        title="Every finding is pinned to a moment, with the numbers behind it."
        lede="A finding carries a start and an end, the measurement that crossed its threshold, how large the deviation was and why it matters to a listener. The explanation is written from the measured values, never invented."
      />
      {featured && sample ? (
        <>
          <ol className="ledger-l" aria-label="Findings in the demo sample">
            {flaws.map((f, i) => (
              <li key={f.flaw_id}>
                <button type="button" className="ledger-l__row" onClick={() => void open(f.flaw_id)}>
                  <span className="ledger-l__no num">{String(i + 1).padStart(2, '0')}</span>
                  <span className="ledger-l__when num">{fmtClock(f.start_s, 1)}–{fmtClock(f.end_s, 1)}</span>
                  <FlawTag type={f.type} />
                  <span className="ledger-l__ev num">{evidenceHeadline(f)}</span>
                  <span className="ledger-l__sev" title={`Severity ${f.severity.toFixed(2)} of 1`}><i style={{ width: `${Math.round(f.severity * 100)}%` }} /></span>
                  <Icon name="arrow-right" size={16} />
                </button>
              </li>
            ))}
          </ol>
          <div className="anatomy">
            <div className="anatomy__col">
              <h3 className="lsec__minor">Measured</h3>
              <dl className="anatomy__rows">
                {evidenceRows(featured).slice(0, 5).map((row) => (
                  <div key={row.label}><dt>{row.label}</dt><dd className="num">{row.value}{row.unit ? <span className="muted"> {row.unit}</span> : null}</dd></div>
                ))}
              </dl>
            </div>
            <div className="anatomy__col">
              <h3 className="lsec__minor">Why it counts</h3>
              <Prose text={featured.explanation} />
            </div>
            <div className="anatomy__col">
              <h3 className="lsec__minor">What to try</h3>
              <Prose text={featured.recommendation} />
            </div>
          </div>
          <p className="lsec__fine">
            From the demo sample, a synthetic voice analysed by the real pipeline: {flawMeta(featured.type).label.toLowerCase()} at {fmtClock(featured.start_s, 1)}.
            {' '}Open any row to see it in the analysis.
          </p>
        </>
      ) : (
        <p className="lsec__fine">
          {demo.status === 'loading' ? 'Loading the demo sample…' : 'The demo sample is not installed here. Analyse a recording below to see findings with their evidence.'}
        </p>
      )}
    </section>
  );
}

const STEPS: { icon: IconName; title: string; text: string }[] = [
  { icon: 'upload', title: 'Bring a recording', text: 'Upload a WAV or MP3, or record in the browser. Pick the passage it reads: its baseline decides what counts as effective delivery.' },
  { icon: 'text', title: 'Align and measure', text: 'Speech recognition and forced alignment give every word a start and an end. Pitch, loudness, speech rate and pauses are measured word by word.' },
  { icon: 'ruler', title: 'Compare with the baseline', text: 'Each measurement is compared with how the baseline readings delivered the same words. A run that stays far enough away, for long enough, becomes a finding.' },
  { icon: 'flag', title: 'Read the evidence', text: 'Open the timeline, play any finding, and read the measured values, the reason and a suggestion. Print the report or export the data.' },
];

function Journey() {
  return (
    <section id="journey" className="lsec" aria-labelledby="journey-title">
      <SectionHead id="journey" title="From a recording to an explanation, in four steps." />
      <ol className="journey">
        {STEPS.map((s, i) => (
          <li key={s.title} className="journey__step">
            <span className="journey__no num">{String(i + 1).padStart(2, '0')}</span>
            <span className="journey__icon"><Icon name={s.icon} size={20} /></span>
            <h3 className="journey__title">{s.title}</h3>
            <p>{s.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Footer() {
  const go = (path: string) => (e: MouseEvent) => { e.preventDefault(); navigate(path); };
  return (
    <footer className="lfoot">
      <div className="lfoot__inner">
        <div>
          <div className="lfoot__brand">VAANI</div>
          <p>Contrastive speech analytics and temporal flaw grounding.</p>
          <p className="muted">Track C · IIT Mandi Multimodal AI Hackathon 2026</p>
        </div>
        <nav aria-label="Footer" className="lfoot__links">
          <a href="#/library" onClick={go('/library')}>Library</a>
          <a href="#/custom" onClick={go('/custom')}>Custom passage</a>
          <a href="#/settings" onClick={go('/settings')}>Settings</a>
          <a href="#/help" onClick={go('/help')}>Help &amp; shortcuts</a>
        </nav>
      </div>
    </footer>
  );
}

export function Landing({ children }: { children: ReactNode }) {
  const demo = useDemoSample();
  return (
    <div className="landing">
      <Hero demo={demo} />
      <Method />
      <Evidence demo={demo} />
      <Journey />
      <section id="start" className="lsec lsec--start" aria-labelledby="start-title">
        <SectionHead
          id="start"
          title="Analyse a recording"
          lede="Upload a recording of a passage, or record one here. It is compared with a baseline of the same passage, and every deviation is tied to a time, a measurement, a reason and a suggestion."
        />
        {children}
      </section>
      <Footer />
    </div>
  );
}
