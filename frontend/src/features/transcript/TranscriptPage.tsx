import { useEffect, useMemo, useRef } from 'react';
import type { AlignedWord, Flaw } from '@/api/types';
import { Icon } from '@/components/Icon';
import { PageHead } from '@/components/page';
import { Button, Chip, FlawTag, Panel } from '@/components/ui';
import { fmtNum, plural } from '@/lib/format';
import { findFlaw, wordIndexAt, wordsInRange } from '@/lib/result';
import { useTimecode } from '@/lib/settings';
import { useStore } from '@/lib/store';
import { floorIndex } from '@/lib/time';
import { analysisPath, navigate } from '@/app/router';
import { goToFlaw } from '@/state/actions';
import type { LoadedAnalysis } from '@/state/analysis';
import { playerStore, playheadStore, seek } from '@/state/player';
import { selectFlaw, selectionStore } from '@/state/ui';

/** Pixels of extra space drawn after a word per second of silence that follows it (a picture of the pause, not a measurement). */
const GAP_PX_PER_SECOND = 22;

interface PauseAfter {
  duration: number;
  type: string;
}

function usePausesAfterWords(analysis: LoadedAnalysis): Map<number, PauseAfter> {
  return useMemo(() => {
    const words = analysis.result.alignment;
    const ends = words.map((w) => w.end_s);
    const map = new Map<number, PauseAfter>();
    for (const e of analysis.result.features.pause_events) {
      const i = floorIndex(ends, e.start_s + 0.08);
      const word = words[i];
      if (word && Math.abs(word.end_s - e.start_s) <= 0.25) map.set(i, { duration: e.duration_s, type: e.boundary_type });
    }
    return map;
  }, [analysis.result]);
}

function Word({
  index, word, active, flaws, selected, gap, onClick,
}: { index: number; word: AlignedWord; active: boolean; flaws: Flaw[]; selected: boolean; gap: PauseAfter | undefined; onClick: (word: AlignedWord) => void }) {
  const first = flaws[0];
  const title = `${word.word}  ·  ${fmtNum(word.start_s, 2)}–${fmtNum(word.end_s, 2)} s  ·  confidence ${fmtNum(word.confidence, 2)}${flaws.length ? `\n${flaws.map((f) => `${f.flaw_id}: ${f.type.replace(/_/g, ' ')}`).join(', ')}` : ''}`;
  return (
    <>
      <span
        id={`w-${index}`}
        role="button"
        tabIndex={0}
        className={`tword ${active ? 'is-active' : ''} ${first ? 'has-flaw' : ''} ${selected ? 'is-selected' : ''}`}
        style={{ ['--c' as string]: first ? `var(--f-${first.type})` : undefined, ['--low' as string]: String(1 - Math.min(1, Math.max(0, word.confidence))) }}
        title={title}
        data-index={index}
        onClick={() => onClick(word)}
        onKeyDown={(e) => { if (e.key === 'Enter') onClick(word); }}
      >
        {word.word}
      </span>
      {gap ? (
        <span className={`tgap tgap--${gap.type}`} role="img" style={{ width: `${Math.max(3, gap.duration * GAP_PX_PER_SECOND)}px` }} title={`${fmtNum(gap.duration, 2)} s pause`} aria-label={`${fmtNum(gap.duration, 2)} second pause`} />
      ) : ' '}
    </>
  );
}

export function TranscriptPage({ analysis }: { analysis: LoadedAnalysis }) {
  const { result } = analysis;
  const tc = useTimecode();
  const words = result.alignment;
  const activeIndex = useStore(playheadStore, (t) => wordIndexAt(words, t));
  const playing = useStore(playerStore, (s) => s.playing);
  const hasAudio = useStore(playerStore, (s) => s.src !== null);
  const selectedId = useStore(selectionStore, (s) => s.flawId);
  const selected = findFlaw(result, selectedId);
  const gaps = usePausesAfterWords(analysis);
  const flawsAtWord = useMemo(() => {
    const map = new Map<number, Flaw[]>();
    for (const f of result.flaws) for (const i of wordsInRange(words, f.start_s, f.end_s)) map.set(i, [...(map.get(i) ?? []), f]);
    return map;
  }, [result.flaws, words]);
  const selectedWords = useMemo(() => new Set(selected ? wordsInRange(words, selected.start_s, selected.end_s) : []), [selected, words]);
  const body = useRef<HTMLDivElement>(null);

  // Follow the spoken word while playing.
  useEffect(() => {
    if (!playing || activeIndex < 0) return;
    document.getElementById(`w-${activeIndex}`)?.scrollIntoView({ block: 'center', behavior: 'auto' });
  }, [activeIndex, playing]);

  // Bring a selected finding into view.
  useEffect(() => {
    if (!selected) return;
    const first = wordsInRange(words, selected.start_s, selected.end_s)[0];
    if (first !== undefined) document.getElementById(`w-${first}`)?.scrollIntoView({ block: 'center', behavior: 'auto' });
  }, [selected?.flaw_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const onWord = (word: AlignedWord) => { if (hasAudio) seek(word.start_s); };

  return (
    <div className="page">
      <PageHead
        eyebrow="Words and timing"
        title="Transcript"
        meta={(
          <>
            <span>{plural(words.length, 'aligned word')}</span>
            <span>{result.processing_meta.transcript_source === 'manual' ? 'transcript supplied manually' : 'recognised from the audio'}</span>
            <span>alignment: {result.alignment_method.replace(/_/g, ' ')}</span>
          </>
        )}
      />
      <div className="transcript">
        <article className="transcript__text" ref={body} aria-label="Transcript with timing">
          <p className="transcript__flow">
            {words.map((w, i) => (
              <Word
                key={i}
                index={i}
                word={w}
                active={i === activeIndex && hasAudio}
                flaws={flawsAtWord.get(i) ?? []}
                selected={selectedWords.has(i)}
                gap={gaps.get(i)}
                onClick={onWord}
              />
            ))}
          </p>
        </article>
        <aside className="transcript__side">
          <Panel eyebrow="Reading it" title="Legend">
            <ul className="legend legend--plain">
              <li><span className="tword-demo">word</span><span>Click a word to play from there. The word being spoken is outlined while the audio plays.</span></li>
              <li><span className="tword-demo tword-demo--flaw">word</span><span>A coloured underline marks the words inside a finding; the colour is the finding’s type.</span></li>
              <li><span className="tword-demo tword-demo--faint">word</span><span>A warm tint marks words aligned with lower confidence; the lower, the stronger.</span></li>
              <li><span className="tgap-demo" /><span>The space after a word is stretched in proportion to the pause that follows it.</span></li>
            </ul>
          </Panel>
          <Panel eyebrow="Jump to" title={plural(result.flaws.length, 'finding')}>
            {result.flaws.length === 0 ? <p className="muted">No findings.</p> : (
              <ul className="jump">
                {result.flaws.map((f) => (
                  <li key={f.flaw_id}>
                    <button type="button" className={`jump__item ${f.flaw_id === selectedId ? 'is-active' : ''}`} onClick={() => { selectFlaw(f.flaw_id === selectedId ? null : f.flaw_id); }}>
                      <FlawTag type={f.type} />
                      <span className="num">{tc.range(f.start_s, f.end_s)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {selected ? (
              <div className="jump__actions">
                {hasAudio ? <Button size="sm" variant="secondary" icon="play" onClick={() => goToFlaw(selected, { play: true })}>Play</Button> : null}
                <Button size="sm" variant="ghost" iconRight="arrow-right" onClick={() => navigate(analysisPath(analysis.id, 'flaws', selected.flaw_id))}>Evidence</Button>
              </div>
            ) : null}
          </Panel>
          {!hasAudio ? <Chip icon="info">No audio for this analysis</Chip> : null}
          <p className="transcript__recognised"><Icon name="text" size={14} /> <span>Recognised text, exactly as returned: “{result.transcript}”</span></p>
        </aside>
      </div>
    </div>
  );
}
