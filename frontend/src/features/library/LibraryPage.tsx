import { useEffect, useMemo, useState } from 'react';
import type { HistoryEntry } from '@/state/history';
import type { SampleIndex } from '@/api/types';
import { Icon } from '@/components/Icon';
import { PageHead, SourceChip } from '@/components/page';
import { Button, Dialog, EmptyState, IconButton, Meter, Panel, ScrollRegion } from '@/components/ui';
import { fmtDuration, fmtNum, fmtRelative, plural } from '@/lib/format';
import { analysisPath, navigate } from '@/app/router';
import { openNewAnalysis } from '@/features/landing/LandingNav';
import { loadSamples } from '@/state/analysis';
import { clearHistory, removeHistory, useHistory } from '@/state/history';
import { SampleCard } from '../analyze/SampleCard';

function HistoryTable({ entries }: { entries: HistoryEntry[] }) {
  return (
    <ScrollRegion label="Your analyses" className="table-scroll--tall">
      <table className="table">
        <thead>
          <tr><th>Analysis</th><th>Source</th><th className="r">Score</th><th className="r">Findings</th><th className="r">Length</th><th>Baseline</th><th>Opened</th><th aria-label="Actions" /></tr>
        </thead>
        <tbody>
          {entries.map((h) => (
            <tr key={h.id} className="row-link" onClick={() => navigate(analysisPath(h.id, 'overview'))}>
              <td>
                <button type="button" className="link-btn lib__title" onClick={(e) => { e.stopPropagation(); navigate(analysisPath(h.id, 'overview')); }}>{h.title}</button>
              </td>
              <td><SourceChip source={h.source} /></td>
              <td className="r">
                <span className="lib__score"><span className="num">{fmtNum(h.composite, 1)}</span><span className="lib__meter"><Meter value={h.composite} label={`Score ${fmtNum(h.composite, 1)}`} /></span></span>
              </td>
              <td className="num r">{h.flawCount}</td>
              <td className="num r">{fmtDuration(h.durationS)}</td>
              <td className="num muted">{h.baselineId}</td>
              <td className="muted nowrap">{fmtRelative(h.openedAt)}</td>
              <td className="r"><IconButton icon="trash" label={`Remove ${h.title} from this list`} size={15} onClick={(e) => { e.stopPropagation(); removeHistory(h.id); }} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

export function LibraryPage() {
  const history = useHistory();
  const [samples, setSamples] = useState<SampleIndex | null>(null);
  const [query, setQuery] = useState('');
  const [openId, setOpenId] = useState('');
  const [confirm, setConfirm] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadSamples().then((s) => !cancelled && setSamples(s)).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const q = query.trim().toLowerCase();
  const shownHistory = useMemo(() => history.filter((h) => !q || `${h.title} ${h.baselineId} ${h.source}`.toLowerCase().includes(q)), [history, q]);
  const shownSamples = useMemo(() => (samples?.samples ?? []).filter((s) => !q || `${s.title} ${s.description}`.toLowerCase().includes(q)), [samples, q]);

  const submitId = (e: React.FormEvent) => {
    e.preventDefault();
    const id = openId.trim();
    if (id && !/[\s/#?]/.test(id)) navigate(analysisPath(id, 'overview'));
  };

  return (
    <div className="page">
      <PageHead
        eyebrow="Library"
        title="Samples and your analyses"
        meta={<span>Demo samples ship with the dashboard. Analyses you open are listed here, in this browser only; the results themselves stay on the server.</span>}
        actions={<Button variant="primary" icon="plus" onClick={openNewAnalysis}>New analysis</Button>}
      />

      <div className="lib__bar">
        <label className="lib__search">
          <Icon name="search" size={16} />
          <input className="lib__input" type="search" placeholder="Filter by title, baseline or source" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Filter the library" />
        </label>
        <form className="lib__open" onSubmit={submitId}>
          <input className="input num" placeholder="Open a stored analysis by id" value={openId} onChange={(e) => setOpenId(e.target.value)} aria-label="Analysis id" spellCheck={false} />
          <Button type="submit" variant="secondary" disabled={!openId.trim()}>Open</Button>
        </form>
      </div>

      <section aria-label="Demo samples">
        <div className="section-head"><span className="eyebrow">Demo samples</span><h3>{samples ? plural(shownSamples.length, 'synthetic recording') : 'Synthetic recordings'}</h3></div>
        {samples === null ? <p className="muted">Loading the samples…</p> : shownSamples.length === 0 ? <p className="muted">No sample matches “{query}”.</p> : (
          <ul className="samples samples--grid">{shownSamples.map((s) => <SampleCard key={s.id} sample={s} />)}</ul>
        )}
        {samples ? <p className="lib__note">A synthetic voice read one passage, with deliberate flaws where marked. They show the interface and the evidence trail; they are not a measure of detection accuracy.</p> : null}
      </section>

      <Panel eyebrow="This browser" title={history.length === 0 ? 'Your analyses' : `Your analyses (${shownHistory.length}${shownHistory.length !== history.length ? ` of ${history.length}` : ''})`} actions={history.length > 0 ? <Button size="sm" variant="ghost" icon="trash" onClick={() => setConfirm(true)}>Clear list</Button> : null} flush>
        {history.length === 0 ? (
          <EmptyState icon="layers" title="Nothing here yet" action={<Button variant="primary" onClick={openNewAnalysis}>Analyse a recording</Button>}>
            Recordings you analyse, and samples you open, appear here so you can come back to them.
          </EmptyState>
        ) : shownHistory.length === 0 ? <p className="lib__empty muted">Nothing in your list matches “{query}”.</p> : <HistoryTable entries={shownHistory} />}
      </Panel>

      <Dialog open={confirm} onClose={() => setConfirm(false)} title="Clear the list?">
        <p className="prose">This removes {plural(history.length, 'entry', 'entries')} from this browser’s list. The analyses stay on the server and can be opened again by id.</p>
        <div className="dialog__actions">
          <Button variant="ghost" onClick={() => setConfirm(false)}>Keep them</Button>
          <Button variant="danger" icon="trash" onClick={() => { clearHistory(); setConfirm(false); }}>Clear the list</Button>
        </div>
      </Dialog>
    </div>
  );
}
