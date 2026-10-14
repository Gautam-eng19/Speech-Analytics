import '@testing-library/jest-dom/vitest';
import { configure } from '@testing-library/react';

// Rendering the demo samples parses large JSON in jsdom; allow slow CI machines a little more time than the 1 s default.
configure({ asyncUtilTimeout: 4000 });

// jsdom has no layout, media or storage-quota behaviour; these stand-ins keep components that touch them from throwing.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
// jsdom has no PointerEvent; a MouseEvent with the pointer fields is enough for the components under test.
if (typeof window.PointerEvent === 'undefined') {
  class PointerEventStandIn extends MouseEvent {
    pointerId: number;
    pointerType: string;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
      this.pointerType = init.pointerType ?? 'mouse';
    }
  }
  window.PointerEvent = PointerEventStandIn as unknown as typeof PointerEvent;
}
Element.prototype.scrollIntoView = () => undefined;
HTMLElement.prototype.setPointerCapture = () => undefined;
HTMLElement.prototype.releasePointerCapture = () => undefined;
HTMLMediaElement.prototype.load = () => undefined;
HTMLMediaElement.prototype.pause = () => undefined;
HTMLMediaElement.prototype.play = () => Promise.resolve();
URL.createObjectURL = () => 'blob:test';
URL.revokeObjectURL = () => undefined;

afterEach(() => {
  localStorage.clear();
  window.location.hash = '';
});
