import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { ScoreRadar, axisAngle, radarPoint, type RadarDim } from '@/charts/ScoreRadar';

const DIMS: RadarDim[] = [
  { key: 'speech_rate', label: 'Speech rate', score: 84, weight: 0.3, flawCount: 1, penalty: 16 },
  { key: 'pauses', label: 'Pauses', score: 77.4, weight: 0.25, flawCount: 1, penalty: 22.6 },
  { key: 'energy', label: 'Energy', score: 100, weight: 0.2, flawCount: 0, penalty: 0 },
  { key: 'pitch', label: 'Pitch', score: null, weight: 0, flawCount: 0, penalty: 0, reason: 'The baseline has no pitch profile.' },
];

function Harness({ dims = DIMS, onOpen = () => undefined }: { dims?: RadarDim[]; onOpen?: (key: string) => void }) {
  const [active, setActive] = useState<string | null>(null);
  return <ScoreRadar dims={dims} activeKey={active} onActive={setActive} onOpen={onOpen} openHint="Click to open its strongest finding" label="Score profile" />;
}

describe('radar geometry', () => {
  it('puts the first spoke at twelve o\'clock and goes clockwise', () => {
    expect(axisAngle(0, 4)).toBeCloseTo(-Math.PI / 2);
    expect(axisAngle(1, 4)).toBeCloseTo(0);
    expect(axisAngle(2, 4)).toBeCloseTo(Math.PI / 2);
  });
  it('places a value on its spoke: 100 on the ring, 0 in the centre, 50 half way, and clamps', () => {
    const top = radarPoint(200, 200, 100, axisAngle(0, 4), 100);
    expect(top.x).toBeCloseTo(200);
    expect(top.y).toBeCloseTo(100);
    expect(radarPoint(200, 200, 100, axisAngle(1, 4), 50)).toEqual({ x: 250, y: 200 + 0 * 1 });
    expect(radarPoint(200, 200, 100, axisAngle(2, 4), 0)).toEqual({ x: 200, y: 200 });
    expect(radarPoint(200, 200, 100, axisAngle(1, 4), 140).x).toBeCloseTo(300);
    expect(radarPoint(200, 200, 100, axisAngle(1, 4), -5).x).toBeCloseTo(200);
  });
});

describe('ScoreRadar', () => {
  it('draws one labelled spoke per dimension with the backend\'s value, and no corner for a dimension that was not scored', () => {
    const { container } = render(<Harness />);
    const group = screen.getByRole('group', { name: 'Score profile' });
    const axes = within(group).getAllByRole('button');
    expect(axes).toHaveLength(4);
    expect(axes[0]).toHaveAccessibleName('Speech rate: 84.0 out of 100, 1 finding. Press Enter to open the strongest one.');
    expect(axes[2]).toHaveAccessibleName('Energy: 100.0 out of 100, 0 findings.');
    expect(axes[3]).toHaveAccessibleName('Pitch: not scored. The baseline has no pitch profile.');
    expect(group).toHaveTextContent('not scored');
    expect(container.querySelectorAll('.radar__dot')).toHaveLength(3);
    expect(container.querySelectorAll('.radar__dot.has-findings')).toHaveLength(2);       // marked, and not by colour alone: the readout and the list say it too
    expect(container.querySelectorAll('.radar__spoke.is-off')).toHaveLength(1);
    expect(container.querySelector('.radar__area')).not.toBeNull();                       // three corners make a shape
  });

  it('shows what a dimension lost when it is pointed at and clears when the pointer leaves', () => {
    const { container } = render(<Harness />);
    const readout = () => container.querySelector('.radar__readout')!;
    expect(readout()).toHaveTextContent('Point at a spoke');
    fireEvent.pointerEnter(screen.getByRole('button', { name: /^Speech rate/ }));
    expect(readout()).toHaveTextContent('Speech rate84.0 / 100lost 16.0 points · weight 30 % · 1 finding');
    expect(readout()).toHaveTextContent('Click to open its strongest finding');
    expect(container.querySelector('.radar__gap.is-active')).not.toBeNull();
    fireEvent.pointerLeave(container.querySelector('svg')!);
    expect(readout()).toHaveTextContent('Point at a spoke');
    expect(container.querySelector('.radar__gap.is-active')).toBeNull();
  });

  it('says there is nothing lost for a perfect dimension, and why for a dimension that was not scored', () => {
    const { container } = render(<Harness />);
    fireEvent.pointerEnter(screen.getByRole('button', { name: /^Energy/ }));
    expect(container.querySelector('.radar__readout')).toHaveTextContent('nothing lost · weight 20 % · 0 findings');
    expect(container.querySelector('.radar__readout')).not.toHaveTextContent('Click to open');
    fireEvent.pointerEnter(screen.getByRole('button', { name: /^Pitch/ }));
    expect(container.querySelector('.radar__readout')).toHaveTextContent('The baseline has no pitch profile.');
  });

  it('opens a dimension on click, Enter and Space, and moves between spokes with the arrow keys', () => {
    const onOpen = vi.fn();
    render(<Harness onOpen={onOpen} />);
    const [rate, pauses] = screen.getAllByRole('button');
    fireEvent.click(rate!);
    expect(onOpen).toHaveBeenLastCalledWith('speech_rate');
    act(() => rate!.focus());
    fireEvent.keyDown(rate!, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(pauses);
    fireEvent.keyDown(pauses!, { key: 'Enter' });
    expect(onOpen).toHaveBeenLastCalledWith('pauses');
    fireEvent.keyDown(pauses!, { key: ' ' });
    expect(onOpen).toHaveBeenCalledTimes(3);
    fireEvent.keyDown(pauses!, { key: 'ArrowLeft' });
    expect(document.activeElement).toBe(rate);
    fireEvent.keyDown(rate!, { key: 'ArrowLeft' });                                        // wraps round
    expect(document.activeElement).toBe(screen.getAllByRole('button')[3]);
    fireEvent.keyDown(document.activeElement!, { key: 'Home' });
    expect(document.activeElement).toBe(rate);
    fireEvent.keyDown(rate!, { key: 'End' });
    expect(document.activeElement).toBe(screen.getAllByRole('button')[3]);
  });

  it('keeps one tab stop, and focusing a spoke shows its readout like hovering does', () => {
    const { container } = render(<Harness />);
    const axes = screen.getAllByRole('button');
    expect(axes.filter((a) => a.getAttribute('tabindex') === '0')).toHaveLength(1);
    fireEvent.focus(axes[1]!);
    expect(container.querySelector('.radar__readout')).toHaveTextContent('Pauses');
    expect(axes.filter((a) => a.getAttribute('tabindex') === '0')[0]).toBe(axes[1]);
    fireEvent.blur(axes[1]!);
    expect(container.querySelector('.radar__readout')).toHaveTextContent('Point at a spoke');
  });

  it('does not invent a shape from fewer than three scored dimensions', () => {
    const two = DIMS.map((d, i) => (i === 2 ? { ...d, score: null } : d));
    const { container, rerender } = render(<Harness dims={two} />);
    expect(container.querySelector('.radar__area')).toBeNull();
    expect(container.querySelector('.radar__edge')).not.toBeNull();                       // two corners are joined by a line
    expect(container.querySelectorAll('.radar__dot')).toHaveLength(2);
    rerender(<Harness dims={DIMS.map((d, i) => (i === 0 ? d : { ...d, score: null }))} />);
    expect(container.querySelector('.radar__edge')).toBeNull();
    expect(container.querySelectorAll('.radar__dot')).toHaveLength(1);
  });

  it('puts every corner at the radius its score says', () => {
    const { container } = render(<Harness />);
    const dots = Array.from(container.querySelectorAll('.radar__dot')).map((c) => ({ x: Number(c.getAttribute('cx')), y: Number(c.getAttribute('cy')) }));
    const spokes = Array.from(container.querySelectorAll('.radar__spoke:not(.is-off)')).map((l) => ({ x2: Number(l.getAttribute('x2')), y2: Number(l.getAttribute('y2')), x1: Number(l.getAttribute('x1')), y1: Number(l.getAttribute('y1')) }));
    [84, 77.4, 100].forEach((score, i) => {
      const full = Math.hypot(spokes[i]!.x2 - spokes[i]!.x1, spokes[i]!.y2 - spokes[i]!.y1);
      const got = Math.hypot(dots[i]!.x - spokes[i]!.x1, dots[i]!.y - spokes[i]!.y1);
      expect(got / full).toBeCloseTo(score / 100, 2);
    });
  });
});
