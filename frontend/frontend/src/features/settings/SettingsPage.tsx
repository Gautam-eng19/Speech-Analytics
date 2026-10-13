import { useState } from 'react';
import { CLIENT_CONTRACT_VERSION } from '@/api/client';
import { Icon } from '@/components/Icon';
import { PageHead } from '@/components/page';
import { Button, Chip, Dialog, Panel, Segmented, Switch, ToggleChip } from '@/components/ui';
import { DEFAULT_SETTINGS, LANE_TOGGLES, updateSettings, useSettings, type LaneToggle } from '@/lib/settings';
import { plural } from '@/lib/format';
import { checkConnection, useConnection } from '@/state/connection';
import { clearHistory, useHistory } from '@/state/history';
import { pushToast, setOverlay } from '@/state/ui';

const LANE_LABEL: Record<LaneToggle, string> = { words: 'Words', loudness: 'Loudness', pitch: 'Pitch', rate: 'Speech rate', pauses: 'Pauses' };

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="setting">
      <div className="setting__text">
        <div className="setting__label">{label}</div>
        {hint ? <div className="setting__hint">{hint}</div> : null}
      </div>
      <div className="setting__control">{children}</div>
    </div>
  );
}

export function SettingsPage() {
  const settings = useSettings();
  const connection = useConnection();
  const history = useHistory();
  const [base, setBase] = useState(settings.apiBase);
  const [testing, setTesting] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const health = connection.health;
  const majorMismatch = health ? health.api_contract_version.split('.')[0] !== CLIENT_CONTRACT_VERSION.split('.')[0] : false;

  const saveBase = async () => {
    updateSettings({ apiBase: base.trim().replace(/\/+$/, '') });
    setTesting(true);
    await checkConnection();
    setTesting(false);
  };

  return (
    <div className="page page--narrow">
      <PageHead eyebrow="System" title="Settings" meta={<span>Saved in this browser only.</span>} />

      <Panel eyebrow="Look and feel" title="Appearance">
        <div className="settings">
          <Row label="Theme" hint="System follows your operating system.">
            <Segmented label="Theme" value={settings.theme} onChange={(theme) => updateSettings({ theme })} options={[{ value: 'light', label: 'Light', icon: 'sun' }, { value: 'system', label: 'System', icon: 'monitor' }, { value: 'dark', label: 'Dark', icon: 'moon' }]} />
          </Row>
          <Row label="Density" hint="Compact fits more on a screen.">
            <Segmented label="Density" value={settings.density} onChange={(density) => updateSettings({ density })} options={[{ value: 'comfortable', label: 'Comfortable' }, { value: 'compact', label: 'Compact' }]} />
          </Row>
          <Row label="Motion" hint="Reduce switches off transitions and animation.">
            <Segmented label="Motion" value={settings.motion} onChange={(motion) => updateSettings({ motion })} options={[{ value: 'system', label: 'System' }, { value: 'reduce', label: 'Reduce' }]} />
          </Row>
          <Row label="Time format" hint="How times are written: 1:05.3 or 65.3 s.">
            <Segmented label="Time format" value={settings.timecode} onChange={(timecode) => updateSettings({ timecode })} options={[{ value: 'clock', label: '1:05.3' }, { value: 'seconds', label: '65.3 s' }]} />
          </Row>
        </div>
      </Panel>

      <Panel eyebrow="Analysis views" title="Timeline">
        <div className="settings">
          <Row label="Follow the playhead" hint="Scroll the timeline along while the audio plays.">
            <Switch checked={settings.followPlayhead} onChange={(followPlayhead) => updateSettings({ followPlayhead })} label="Follow the playhead" />
          </Row>
          <Row label="Show ground truth on samples" hint="Draw where each synthetic sample was given a known flaw, and whether the analysis found it.">
            <Switch checked={settings.showGroundTruth} onChange={(showGroundTruth) => updateSettings({ showGroundTruth })} label="Show ground truth on samples" />
          </Row>
          <Row label="Lanes" hint="Which signals the timeline draws.">
            <div className="chip-row">
              {LANE_TOGGLES.map((lane) => <ToggleChip key={lane} on={settings.lanes[lane]} onChange={(on) => updateSettings({ lanes: { ...settings.lanes, [lane]: on } })}>{LANE_LABEL[lane]}</ToggleChip>)}
            </div>
          </Row>
        </div>
      </Panel>

      <Panel eyebrow="Backend" title="Connection" actions={<Chip tone={connection.status === 'online' ? 'good' : connection.status === 'offline' ? 'bad' : 'neutral'}>{connection.status === 'online' ? 'Online' : connection.status === 'offline' ? 'Offline' : 'Checking'}</Chip>}>
        <div className="settings">
          <Row label="API address" hint="Leave empty to use the server that delivered this page. Set it only if the API runs elsewhere (it must allow this origin).">
            <form className="setting__form" onSubmit={(e) => { e.preventDefault(); void saveBase(); }}>
              <input className="input num" value={base} onChange={(e) => setBase(e.target.value)} placeholder="same origin" aria-label="API address" spellCheck={false} />
              <Button type="submit" variant="secondary" busy={testing}>Save and test</Button>
            </form>
          </Row>
          <Row label="Server versions" hint="Reported by the API's health check.">
            {health ? (
              <dl className="versions num">
                <div><dt>API contract</dt><dd>{health.api_contract_version}</dd></div>
                <div><dt>Configuration</dt><dd>{health.config_version}</dd></div>
                <div><dt>Pipeline</dt><dd>{health.pipeline_version}</dd></div>
                <div><dt>Dashboard built for</dt><dd>{CLIENT_CONTRACT_VERSION}</dd></div>
              </dl>
            ) : <span className="muted">Not reachable.</span>}
            {majorMismatch ? <p className="form-error"><Icon name="alert-triangle" size={15} /> The server’s API contract has a different major version than this dashboard expects. Some views may not work.</p> : null}
          </Row>
        </div>
      </Panel>

      <Panel eyebrow="This browser" title="Data">
        <div className="settings">
          <Row label="Recent analyses" hint={`${plural(history.length, 'entry', 'entries')} in the list. Results stay on the server; only titles and scores are kept here.`}>
            <Button variant="secondary" icon="trash" disabled={history.length === 0} onClick={() => { clearHistory(); pushToast('The list was cleared.', 'success', 2200); }}>Clear the list</Button>
          </Row>
          <Row label="Keyboard shortcuts" hint="Everything has a key. Press ? anywhere.">
            <Button variant="secondary" icon="keyboard" onClick={() => setOverlay({ shortcuts: true })}>Show shortcuts</Button>
          </Row>
          <Row label="Reset settings" hint="Back to the defaults above.">
            <Button variant="danger" onClick={() => setConfirmReset(true)}>Reset settings</Button>
          </Row>
        </div>
      </Panel>

      <Dialog open={confirmReset} onClose={() => setConfirmReset(false)} title="Reset all settings?">
        <p className="prose">Theme, density, time format, timeline options and the API address return to their defaults. Your recent analyses are not affected.</p>
        <div className="dialog__actions">
          <Button variant="ghost" onClick={() => setConfirmReset(false)}>Cancel</Button>
          <Button variant="danger" onClick={() => { updateSettings({ ...DEFAULT_SETTINGS }); setBase(''); setConfirmReset(false); void checkConnection(); }}>Reset</Button>
        </div>
      </Dialog>
    </div>
  );
}
