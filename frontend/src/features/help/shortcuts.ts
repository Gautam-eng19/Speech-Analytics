/** The keyboard shortcuts, in one list shared by the shortcuts dialog and the Help page. Keep in sync with app/GlobalKeys.tsx. */
export interface ShortcutGroup {
  group: string;
  items: { keys: string[]; label: string }[];
}

export const SHORTCUTS: ShortcutGroup[] = [
  {
    group: 'Everywhere',
    items: [
      { keys: ['Ctrl', 'K'], label: 'Search and jump to anything (⌘K on Mac)' },
      { keys: ['?'], label: 'Show this list' },
      { keys: ['B'], label: 'Collapse or expand the sidebar' },
      { keys: ['T'], label: 'Switch between light and dark' },
      { keys: ['g', 'n'], label: 'Go to New analysis' },
      { keys: ['g', 'c'], label: 'Go to Custom passage' },
      { keys: ['g', 'l'], label: 'Go to Library' },
      { keys: ['g', 's'], label: 'Go to Settings' },
      { keys: ['g', 'h'], label: 'Go to Help' },
    ],
  },
  {
    group: 'With an analysis open',
    items: [
      { keys: ['1'], label: 'Overview' },
      { keys: ['2'], label: 'Timeline' },
      { keys: ['3'], label: 'Flaws' },
      { keys: ['4'], label: 'Signals' },
      { keys: ['5'], label: 'Transcript' },
      { keys: ['6'], label: 'Baseline & method' },
      { keys: ['E'], label: 'Export the result as JSON' },
    ],
  },
  {
    group: 'Playback',
    items: [
      { keys: ['Space'], label: 'Play or pause' },
      { keys: ['←', '→'], label: 'Seek 1 s back or forward (Shift: 5 s)' },
      { keys: ['Home'], label: 'Back to the start' },
      { keys: ['['], label: 'Previous flaw' },
      { keys: [']'], label: 'Next flaw' },
    ],
  },
  {
    group: 'Timeline',
    items: [
      { keys: ['Scroll'], label: 'Zoom around the pointer' },
      { keys: ['Shift', 'Scroll'], label: 'Pan' },
      { keys: ['Drag'], label: 'Pan the view' },
      { keys: ['Double-click'], label: 'Fit the whole recording' },
      { keys: ['+', '−'], label: 'Zoom in or out' },
      { keys: ['0'], label: 'Fit the whole recording' },
    ],
  },
  {
    group: 'Flaws list',
    items: [
      { keys: ['j', 'k'], label: 'Next or previous flaw in the list' },
      { keys: ['Enter'], label: 'Play the selected flaw' },
      { keys: ['Esc'], label: 'Clear the selection' },
    ],
  },
];
