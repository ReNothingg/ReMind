export const MAX_SPINWHEEL_SEGMENTS = 200;
export const MAX_SPINWHEEL_DURATION_MS = 15_000;

export type SpinwheelConfig = {
  min: number;
  max: number;
  step: number;
  target: number;
  spinTime: number;
};

const asRecord = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === 'object'
    ? value as Record<string, unknown>
    : {};

const finiteNumber = (value: unknown, fallback: number): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

export const normalizeSpinwheelConfig = (initialState: unknown): SpinwheelConfig => {
  const state = asRecord(initialState);
  const range = asRecord(state.range);
  const behavior = asRecord(state.behavior);
  const firstBoundary = finiteNumber(range.min, 1);
  const secondBoundary = finiteNumber(range.max, 100);
  const min = Math.min(firstBoundary, secondBoundary);
  const max = Math.max(firstBoundary, secondBoundary);
  const requestedStep = finiteNumber(range.step, 1);
  const requestedDuration = finiteNumber(behavior.spin_time_ms, 4_200);

  return {
    min,
    max,
    step: requestedStep > 0 ? requestedStep : 1,
    target: finiteNumber(state.number, 50),
    spinTime: Math.min(MAX_SPINWHEEL_DURATION_MS, Math.max(0, requestedDuration)),
  };
};

export const buildSpinwheelSegments = (
  config: Pick<SpinwheelConfig, 'min' | 'max' | 'step' | 'target'>
): number[] => {
  const min = finiteNumber(config.min, 1);
  const max = Math.max(min, finiteNumber(config.max, min));
  const parsedStep = finiteNumber(config.step, 1);
  const step = parsedStep > 0 ? parsedStep : 1;
  const rawLastIndex = Math.floor((max - min) / step);
  const lastIndex = Math.max(
    0,
    Number.isFinite(rawLastIndex) ? rawLastIndex : Number.MAX_SAFE_INTEGER
  );
  const fullCount = lastIndex + 1;

  if (fullCount <= MAX_SPINWHEEL_SEGMENTS) {
    return Array.from({ length: fullCount }, (_, index) =>
      Math.min(max, min + index * step)
    );
  }

  // Large ranges are sampled across their full extent instead of truncating the
  // first values. Always retain the nearest selectable target so the visual
  // result and the announced result cannot disagree.
  const sampledIndexes = Array.from({ length: MAX_SPINWHEEL_SEGMENTS }, (_, index) =>
    Math.round((index * lastIndex) / (MAX_SPINWHEEL_SEGMENTS - 1))
  );
  const clampedTarget = Math.min(max, Math.max(min, finiteNumber(config.target, min)));
  const rawTargetIndex = Math.round((clampedTarget - min) / step);
  const targetIndex = Math.min(
    lastIndex,
    Math.max(0, Number.isFinite(rawTargetIndex) ? rawTargetIndex : 0)
  );

  if (!sampledIndexes.includes(targetIndex)) {
    let replacementIndex = 1;
    for (let index = 2; index < sampledIndexes.length - 1; index += 1) {
      if (
        Math.abs(sampledIndexes[index] - targetIndex)
        < Math.abs(sampledIndexes[replacementIndex] - targetIndex)
      ) {
        replacementIndex = index;
      }
    }
    sampledIndexes[replacementIndex] = targetIndex;
    sampledIndexes.sort((left, right) => left - right);
  }

  const segments = sampledIndexes.map((index) => Math.min(max, min + index * step));
  segments[segments.length - 1] = max;
  return segments;
};
