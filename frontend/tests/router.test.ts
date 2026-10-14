import { describe, expect, it } from 'vitest';
import { analysisPath, parseRoute } from '@/app/router';

describe('parseRoute', () => {
  it('maps the top-level pages', () => {
    expect(parseRoute('')).toEqual({ name: 'analyze' });
    expect(parseRoute('#/')).toEqual({ name: 'analyze' });
    expect(parseRoute('#/library')).toEqual({ name: 'library' });
    expect(parseRoute('#/settings')).toEqual({ name: 'settings' });
    expect(parseRoute('#/help')).toEqual({ name: 'help' });
  });
  it('opens an analysis on its overview by default', () => {
    expect(parseRoute('#/a/abc')).toEqual({ name: 'analysis', id: 'abc', view: 'overview', flawId: null });
  });
  it('reads the view and a flaw id', () => {
    expect(parseRoute('#/a/abc/timeline')).toEqual({ name: 'analysis', id: 'abc', view: 'timeline', flawId: null });
    expect(parseRoute('#/a/abc/flaws/flaw_002')).toEqual({ name: 'analysis', id: 'abc', view: 'flaws', flawId: 'flaw_002' });
  });
  it('ignores a query string', () => {
    expect(parseRoute('#/library?x=1')).toEqual({ name: 'library' });
  });
  it('reports anything else as not found', () => {
    expect(parseRoute('#/nope')).toEqual({ name: 'notfound', path: '/nope' });
    expect(parseRoute('#/a/abc/bogus')).toEqual({ name: 'notfound', path: '/a/abc/bogus' });
    expect(parseRoute('#/a/abc/timeline/extra')).toMatchObject({ name: 'notfound' });
    expect(parseRoute('#/library/extra')).toMatchObject({ name: 'notfound' });
  });
  it('survives malformed percent-encoding', () => {
    expect(parseRoute('#/a/%E0%A4%A/overview')).toMatchObject({ name: 'notfound' });
  });
});

describe('analysisPath', () => {
  it('builds paths that parse back to the same route', () => {
    for (const [id, view, flaw] of [['abc', 'overview', null], ['x y/z', 'flaws', 'flaw_001'], ['8557b6e4-3ac4-5fe3-944d-48b1f48dace1', 'signals', null]] as const) {
      const path = analysisPath(id, view, flaw);
      expect(parseRoute(`#${path}`)).toEqual({ name: 'analysis', id, view, flawId: flaw });
    }
  });
});

describe('the custom passage page', () => {
  it('has its own route and no sub-pages', () => {
    expect(parseRoute('#/custom')).toEqual({ name: 'custom' });
    expect(parseRoute('#/custom/extra')).toMatchObject({ name: 'notfound' });
  });
});
