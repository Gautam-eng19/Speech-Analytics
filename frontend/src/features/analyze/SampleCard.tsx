import type { SampleEntry } from '@/api/types';
import { Icon } from '@/components/Icon';
import { Chip, FlawTag } from '@/components/ui';
import { flawColor } from '@/lib/flawMeta';
import { fmtClock } from '@/lib/format';
import { analysisPath, navigate } from '@/app/router';

/** Mini strip of a sample: where its known flaws were injected along the recording. */
export function SampleStrip({ sample }: { sample: SampleEntry }) {
  return (
    <div className="strip" role="img" aria-label={sample.injected.length ? `Injected flaws: ${sample.injected.map((t) => t.type.replace(/_/g, ' ')).join(', ')}` : 'No flaw injected'}>
      {sample.injected.map((t, i) => (
        <i key={i} className={t.detected ? '' : 'is-missed'} style={{ left: `${(t.start_s / sample.duration_s) * 100}%`, width: `${Math.max(1.2, ((t.end_s - t.start_s) / sample.duration_s) * 100)}%`, ['--c' as string]: flawColor(t.type) }} />
      ))}
    </div>
  );
}

export function SampleCard({ sample }: { sample: SampleEntry }) {
  const types = [...new Set(sample.injected.map((t) => t.type))];
  return (
    <li>
      <button type="button" className="sample" onClick={() => navigate(analysisPath(sample.analysis_id, 'overview'))}>
        <span className="sample__top">
          <span className="sample__title">{sample.title}</span>
          <span className="sample__dur num">{fmtClock(sample.duration_s, 0)}</span>
        </span>
        <span className="sample__desc">{sample.description}</span>
        <SampleStrip sample={sample} />
        <span className="sample__foot">
          {types.length === 0 ? <Chip tone="good" icon="check">Control take</Chip> : types.map((t) => <FlawTag key={t} type={t} compact />)}
          <span className="sample__open">Open <Icon name="arrow-right" size={14} /></span>
        </span>
      </button>
    </li>
  );
}

