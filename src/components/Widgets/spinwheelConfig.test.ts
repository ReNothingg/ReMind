import { describe, expect, it } from 'vitest';
import {
  buildSpinwheelSegments,
  MAX_SPINWHEEL_DURATION_MS,
  MAX_SPINWHEEL_SEGMENTS,
  normalizeSpinwheelConfig,
} from './spinwheelConfig';

describe('spinwheel configuration safety', () => {
  it.each([0, -1, Number.NaN, Number.POSITIVE_INFINITY])(
    'normalizes an unsafe step (%s)',
    (step) => {
      const config = normalizeSpinwheelConfig({ range: { min: 1, max: 5, step } });
      expect(config.step).toBe(1);
      expect(buildSpinwheelSegments(config)).toEqual([1, 2, 3, 4, 5]);
    }
  );

  it('orders reversed boundaries and caps untrusted ranges', () => {
    const config = normalizeSpinwheelConfig({
      range: { min: 1_000_000, max: -1_000_000, step: 0.00001 },
    });
    const segments = buildSpinwheelSegments(config);

    expect(config.min).toBe(-1_000_000);
    expect(config.max).toBe(1_000_000);
    expect(segments).toHaveLength(MAX_SPINWHEEL_SEGMENTS);
    expect(segments[0]).toBe(config.min);
    expect(segments.at(-1)).toBe(config.max);
  });

  it('samples the full range and retains a distant target', () => {
    const targetAtEnd = normalizeSpinwheelConfig({
      range: { min: 1, max: 1_000, step: 1 },
      number: 1_000,
    });
    const targetInMiddle = normalizeSpinwheelConfig({
      range: { min: 1, max: 1_000, step: 1 },
      number: 777,
    });

    expect(buildSpinwheelSegments(targetAtEnd)).toContain(1_000);
    expect(buildSpinwheelSegments(targetInMiddle)).toContain(777);
    expect(buildSpinwheelSegments(targetInMiddle)).toHaveLength(MAX_SPINWHEEL_SEGMENTS);
  });

  it('bounds animation duration from untrusted state', () => {
    expect(normalizeSpinwheelConfig({ behavior: { spin_time_ms: -100 } }).spinTime).toBe(0);
    expect(
      normalizeSpinwheelConfig({ behavior: { spin_time_ms: 999_999 } }).spinTime
    ).toBe(MAX_SPINWHEEL_DURATION_MS);
  });
});
