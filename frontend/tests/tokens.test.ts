import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * WCAG 2.1 AA for the design tokens (src/styles/tokens.css) in both themes. These are the colour pairs the stylesheets actually use,
 * so a token edit that makes text hard to read fails here instead of being noticed on a projector.
 */
// (jsdom replaces the global URL class, which node's fileURLToPath rejects, so resolve the path from the module's string URL.)
const read = (name: string) => readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../src/styles', name), 'utf8');
const tokens = read('tokens.css');

function block(selector: string): Record<string, string> {
  const start = tokens.indexOf(selector);
  const body = tokens.slice(tokens.indexOf('{', start) + 1, tokens.indexOf('\n}', start));
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*([^;]+);/g)].map((m) => [m[1]!, m[2]!.trim()]));
}
const light = block(':root {');
const dark = { ...light, ...block(":root[data-theme='dark']") };

type Rgb = [number, number, number];
const rgb = (hex: string): Rgb => {
  const h = hex.replace('#', '');
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255) as Rgb;
};
const luminance = ([r, g, b]: Rgb) => {
  const f = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
};
const contrast = (a: Rgb, b: Rgb) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
};
const mix = (a: Rgb, b: Rgb, share: number): Rgb => [0, 1, 2].map((i) => a[i]! * share + b[i]! * (1 - share)) as Rgb;

const themes = { light, dark } as const;
const surfaces = ['bg', 'surface', 'surface-2', 'surface-3', 'raised'];
const FLAWS = ['too_fast', 'too_slow', 'excessive_pause', 'low_energy', 'high_energy', 'flat_pitch', 'pitch_instability', 'reduced_clarity'];

describe.each(Object.entries(themes))('%s theme', (_name, t) => {
  const c = (key: string) => rgb(t[key]!);

  it.each(['ink', 'ink-2', 'ink-3'])('%s text reads on every surface (4.5:1)', (ink) => {
    for (const surface of surfaces) expect(contrast(c(ink), c(surface)), `${ink} on ${surface}`).toBeGreaterThanOrEqual(4.5);
  });

  it('decorative strokes and disabled text keep at least 3:1 against the page', () => {
    for (const surface of ['bg', 'surface', 'surface-3']) expect(contrast(c('ink-4'), c(surface)), `ink-4 on ${surface}`).toBeGreaterThanOrEqual(3);
  });

  it('brand and status colours read on their own tinted backgrounds (4.5:1)', () => {
    const pairs: [string, string][] = [['brand', 'brand-soft'], ['brand', 'brand-faint'], ['brand-strong', 'brand-soft'], ['brand', 'surface'], ['on-brand', 'brand'], ['good', 'good-soft'], ['warn', 'warn-soft'], ['bad', 'bad-soft'], ['info', 'info-soft'], ['on-playhead', 'playhead']];
    for (const [fg, bg] of pairs) expect(contrast(c(fg), c(bg)), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
  });

  it('finding-type text, mixed toward the ink as the stylesheets do, reads on its tint in every place it is used', () => {
    const share = Number(/color-mix\(in srgb, var\(--c\) (\d+)%, var\(--ink\)\)/.exec(read('components.css'))![1]) / 100;
    for (const type of FLAWS) {
      const colour = c(`f-${type}`);
      const text = mix(colour, c('ink'), share);
      const places: [string, Rgb][] = [
        ['tag on a panel', mix(colour, c('surface'), 0.11)],
        ['tag on a raised card', mix(colour, c('raised'), 0.11)],
        ['band on the scope', mix(colour, c('scope-bg'), 0.18)],
        ['selected band on the scope', mix(colour, c('scope-bg'), 0.34)],
      ];
      for (const [where, background] of places) expect(contrast(text, background), `${type}, ${where}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('defines every finding colour used by the vocabulary', () => {
    for (const type of FLAWS) expect(t[`f-${type}`], type).toMatch(/^#[0-9a-f]{6}$/i);
  });
});
