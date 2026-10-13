import { Kbd } from '@/components/ui';
import { SHORTCUTS } from './shortcuts';

export function ShortcutList() {
  return (
    <div className="shortcut-grid">
      {SHORTCUTS.map((group) => (
        <section key={group.group}>
          <h3 className="eyebrow shortcut-grid__title">{group.group}</h3>
          <ul>
            {group.items.map((item) => (
              <li key={item.label} className="shortcut-row">
                <span>{item.label}</span>
                <span className="shortcut-row__keys">{item.keys.map((k) => <Kbd key={k}>{k}</Kbd>)}</span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
