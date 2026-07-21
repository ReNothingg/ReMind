import { describe, expect, it } from 'vitest';

import { hasEquivalentWidget } from './widgetUtils';

describe('hasEquivalentWidget', () => {
    it('matches the same widget state even when object keys have a different order', () => {
        const widgets = [
            {
                type: 'beatbox',
                state: { meta: { bars: 1, bpm: 120 }, tracks: [{ instrument: 'kick' }] },
            },
        ];

        expect(
            hasEquivalentWidget(widgets, 'beatbox', {
                tracks: [{ instrument: 'kick' }],
                meta: { bpm: 120, bars: 1 },
            })
        ).toBe(true);
    });

    it('keeps widgets with a different type or state', () => {
        const widgets = [{ type: 'beatbox', state: { meta: { bpm: 120 } } }];

        expect(hasEquivalentWidget(widgets, 'quiz', { meta: { bpm: 120 } })).toBe(false);
        expect(hasEquivalentWidget(widgets, 'beatbox', { meta: { bpm: 140 } })).toBe(false);
    });
});
