import { useEffect, type ReactNode } from 'react';
import { EmptyState, Button } from '@/components/ui';
import { AnalyzePage } from '@/features/analyze/AnalyzePage';
import { BaselinePage } from '@/features/baseline/BaselinePage';
import { CustomPage } from '@/features/custom/CustomPage';
import { FlawsPage } from '@/features/flaws/FlawsPage';
import { HelpPage } from '@/features/help/HelpPage';
import { LibraryPage } from '@/features/library/LibraryPage';
import { OverviewPage } from '@/features/overview/OverviewPage';
import { ReportPage } from '@/features/report/ReportPage';
import { SettingsPage } from '@/features/settings/SettingsPage';
import { SignalsPage } from '@/features/signals/SignalsPage';
import { TimelinePage } from '@/features/timeline/TimelinePage';
import { TranscriptPage } from '@/features/transcript/TranscriptPage';
import { Skeleton } from '@/components/ui';
import { bindSettingsToDocument } from '@/lib/settings';
import { openById, useAnalysis, type LoadedAnalysis } from '@/state/analysis';
import { startConnectionPolling } from '@/state/connection';
import { useCurrent } from '@/state/analysis';
import { bindRouter, navigate, useRoute, VIEW_LABEL, type Route } from './router';
import { Shell } from './Shell';

type AnalysisRoute = Extract<Route, { name: 'analysis' }>;

function LoadingAnalysis() {
  return (
    <div className="page" aria-busy="true" aria-label="Loading analysis">
      <div className="page__head"><Skeleton width={180} height={12} /><Skeleton width={360} height={34} radius={6} /></div>
      <div className="grid-2"><Skeleton height={260} radius={8} /><Skeleton height={260} radius={8} /></div>
    </div>
  );
}

/** Makes sure the analysis named in the URL is open, and shows loading and failure states around the page. */
function AnalysisGate({ route, children }: { route: AnalysisRoute; children: (analysis: LoadedAnalysis) => ReactNode }) {
  const state = useAnalysis();
  useEffect(() => {
    if (state.current?.id !== route.id) void openById(route.id);
    // The id in the URL is the only trigger; the store updates itself.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [route.id]);

  if (state.current && state.current.id === route.id) return <>{children(state.current)}</>;
  if (state.status === 'error' && state.error) {
    return (
      <div className="page">
        <EmptyState
          icon="alert-circle"
          title={state.error.code === 'RESULT_NOT_FOUND' ? 'This analysis is not available' : 'The analysis could not be opened'}
          action={<><Button variant="primary" onClick={() => void openById(route.id)}>Try again</Button><Button onClick={() => navigate('/library')}>Open the library</Button></>}
        >
          {state.error.code === 'RESULT_NOT_FOUND'
            ? 'The server has no stored result with this id (it may have been cleared, or it belongs to another server). Run the analysis again, or open a result from the library.'
            : state.error.detail}
        </EmptyState>
      </div>
    );
  }
  return <LoadingAnalysis />;
}

function Pages() {
  const route = useRoute();
  switch (route.name) {
    case 'analyze': return <AnalyzePage />;
    case 'library': return <LibraryPage />;
    case 'custom': return <CustomPage />;
    case 'settings': return <SettingsPage />;
    case 'help': return <HelpPage />;
    case 'analysis':
      return (
        <AnalysisGate route={route}>
          {(analysis) => {
            switch (route.view) {
              case 'overview': return <OverviewPage analysis={analysis} />;
              case 'timeline': return <TimelinePage analysis={analysis} />;
              case 'flaws': return <FlawsPage analysis={analysis} flawId={route.flawId} />;
              case 'signals': return <SignalsPage analysis={analysis} />;
              case 'transcript': return <TranscriptPage analysis={analysis} />;
              case 'baseline': return <BaselinePage analysis={analysis} />;
              case 'report': return <ReportPage analysis={analysis} />;
            }
          }}
        </AnalysisGate>
      );
    default:
      return (
        <div className="page">
          <EmptyState icon="help" title="Page not found" action={<Button variant="primary" onClick={() => navigate('/')}>Back to start</Button>}>
            There is nothing at <span className="num">#{route.path}</span>.
          </EmptyState>
        </div>
      );
  }
}

/** The browser tab says where you are: page, then the analysis it belongs to. */
function useDocumentTitle(): void {
  const route = useRoute();
  const current = useCurrent();
  useEffect(() => {
    const product = 'VAANI';
    let title = product;
    if (route.name === 'analyze') title = `${product} · Contrastive speech analytics`;
    else if (route.name === 'library') title = `Library · ${product}`;
    else if (route.name === 'custom') title = `Custom passage · ${product}`;
    else if (route.name === 'settings') title = `Settings · ${product}`;
    else if (route.name === 'help') title = `Help · ${product}`;
    else if (route.name === 'notfound') title = `Page not found · ${product}`;
    else if (route.name === 'analysis') title = `${VIEW_LABEL[route.view]} · ${current && current.id === route.id ? current.title : 'Analysis'} · ${product}`;
    document.title = title;
  }, [route, current]);
}

export function App() {
  useDocumentTitle();
  useEffect(() => {
    const unbindSettings = bindSettingsToDocument();
    const unbindRouter = bindRouter();
    const stopPolling = startConnectionPolling();
    return () => { unbindSettings(); unbindRouter(); stopPolling(); };
  }, []);
  const route = useRoute();
  const fill = route.name === 'analysis' && route.view === 'timeline';
  return (
    <Shell fill={fill}>
      <Pages />
    </Shell>
  );
}
