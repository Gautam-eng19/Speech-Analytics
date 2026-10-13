import { Icon, type IconName } from '@/components/Icon';
import { PageHead } from '@/components/page';
import { Panel } from '@/components/ui';
import { ShortcutList } from './ShortcutList';

const GUIDE: { icon: IconName; name: string; text: string }[] = [
  { icon: 'gauge', name: 'Overview', text: 'The deviation score, a one-paragraph readout, the whole recording against the baseline, the findings strongest first, and the notes that limit the result.' },
  { icon: 'gantt', name: 'Timeline', text: 'Every signal on one time axis with the findings above it. Zoom to a moment, play it, and read the values under the pointer.' },
  { icon: 'flag', name: 'Flaws', text: 'One finding at a time: where it is, what was measured against the baseline, why that counts as a flaw, and what to try.' },
  { icon: 'chart', name: 'Signals', text: 'Speech rate, loudness, pitch and pauses as full charts, with tables of the underlying values.' },
  { icon: 'text', name: 'Transcript', text: 'The words with their timing. Click a word to hear it; coloured underlines mark the words inside findings.' },
  { icon: 'ruler', name: 'Baseline and method', text: 'What the recording was compared with, how a finding is made, and what the numbers cannot tell you.' },
];

const GLOSSARY: { term: string; meaning: string }[] = [
  { term: 'Baseline', meaning: 'A reference delivery of the same passage. Each statistic is its mean and spread over the reference recordings. It is not a universal average of speakers.' },
  { term: 'z-score', meaning: 'How many baseline standard deviations a value lies above (+) or below (−) the baseline value. For pace and loudness the baseline value is what the baseline readings did with the same words, and the standard deviation is how much a reading varies over a run of that length; for pauses it is the baseline’s mean and spread. Findings are flagged when a z-score stays beyond a threshold for long enough, and the change is large enough to matter.' },
  { term: 'Severity', meaning: 'How strong a finding is, from 0 to 1, from how far and how long the delivery deviated.' },
  { term: 'Reliability', meaning: 'How much the measurement can be trusted, from 0 to 1 (for example, lower when words are aligned with low confidence).' },
  { term: 'Deviation score', meaning: 'From 0 to 100; 100 means no deviation from the baseline was detected. Each finding subtracts points in proportion to its severity and reliability. It is not a grade of speech quality.' },
  { term: 'Words per minute', meaning: 'Speech rate over a rolling window of words. A silence longer than one second counts as one second, so a long pause is reported as a pause and does not also read as slow speech.' },
  { term: 'dBFS', meaning: 'Decibels relative to digital full scale. 0 is the loudest a file can hold; speech sits well below. Before analysis every recording is scaled so that its typical speech level is the same, so levels are relative: they show louder and quieter stretches inside a recording, not how loudly it was recorded.' },
  { term: 'F0 (pitch)', meaning: 'The fundamental frequency of the voice in hertz, measured only where the voice is voiced.' },
  { term: 'MFCC', meaning: 'Mel-frequency cepstral coefficients: a compact description of the spectral shape of the voice. Shown for reference; not scored.' },
  { term: 'Forced alignment', meaning: 'Matching each transcript word to the moment it was spoken, which gives every finding its start and end time.' },
  { term: 'Synthetic sample', meaning: 'A recording made by a speech synthesiser with flaws injected on purpose, so the analysis can be checked against known truth.' },
];

const FAQ: { q: string; a: string }[] = [
  { q: 'Is anything written by an AI?', a: 'No number is. Every measurement, time, severity and score comes from the deterministic analysis. The explanations are templates that turn those numbers into sentences.' },
  { q: 'Why can a clean take still show findings?', a: 'The detection thresholds are initial values that have not been calibrated on recorded data, and a baseline built from few recordings is noisy. A pause of more than a second can also be flagged on a take that is otherwise clean. Treat findings as indicative until calibration is done; the notes on each analysis say so.' },
  { q: 'Why is there no audio when I reopen an old upload?', a: 'Uploaded audio is analysed in memory and not saved on the server, so only the result is kept. The data is still complete; only playback is missing.' },
  { q: 'How should I record a take in the browser?', a: 'Choose Record now on the New analysis page, read the passage shown, and speak at a steady distance from the microphone in a quiet room. The browser is asked to leave its echo cancellation, noise suppression and automatic gain off, so the take stays as spoken; if it keeps any of them on, the page says so. The take is saved as a 16 kHz mono WAV and sent like any uploaded file. Microphone access needs a secure page: https:// or localhost.' },
  { q: 'Can I take the findings into a spreadsheet?', a: 'Yes. Export CSV on the Flaws page saves one row per finding with the exact values and evidence columns from the analysis. Export result as JSON (command palette, Ctrl or Cmd + K) saves the complete result.' },
  { q: 'Does the score judge what was said?', a: 'No. It compares how the delivery differs from the baseline. Content, wording and argument are not evaluated.' },
  { q: 'Why is pitch not scored?', a: 'The baseline does not yet include a statistic of how much pitch moves inside a window, so flat or unstable pitch cannot be detected. Pitch is drawn for context.' },
];

export function HelpPage() {
  return (
    <div className="page page--narrow">
      <PageHead eyebrow="System" title="Help and shortcuts" meta={<span>How to read an analysis, what the terms mean, and the keys that speed things up.</span>} />

      <section aria-label="How to read an analysis">
        <div className="section-head"><span className="eyebrow">Guide</span><h3>The six views</h3></div>
        <ol className="guide">
          {GUIDE.map((g, i) => (
            <li key={g.name} className="guide__item">
              <span className="guide__icon"><Icon name={g.icon} size={18} /></span>
              <div>
                <div className="guide__name">{g.name} <span className="guide__key num">{i + 1}</span></div>
                <p>{g.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <Panel eyebrow="Reference" title="Keyboard shortcuts">
        <ShortcutList />
      </Panel>

      <Panel eyebrow="Reference" title="Glossary">
        <dl className="glossary">
          {GLOSSARY.map((g) => (
            <div key={g.term} className="glossary__row"><dt>{g.term}</dt><dd>{g.meaning}</dd></div>
          ))}
        </dl>
      </Panel>

      <Panel eyebrow="Good to know" title="Questions">
        <dl className="glossary">
          {FAQ.map((f) => (
            <div key={f.q} className="glossary__row glossary__row--q"><dt>{f.q}</dt><dd>{f.a}</dd></div>
          ))}
        </dl>
      </Panel>
    </div>
  );
}
