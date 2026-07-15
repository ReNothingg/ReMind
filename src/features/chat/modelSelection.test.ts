import { describe, expect, it } from 'vitest';
import {
    normalizeThinkingLevel,
    normalizeModelOptions,
} from './modelSelection';

describe('model thinking levels', () => {
    it('normalizes the supported Flash-Lite levels and medium default', () => {
        const models = normalizeModelOptions([
            {
                id: 'base',
                title: 'Gemini 3.1 Flash Lite',
                subtitle: 'Fast model',
                thinkingLevels: ['MINIMAL', 'low', 'medium', 'high', 'invalid'],
                defaultThinkingLevel: 'medium',
            },
        ]);

        expect(models).toEqual([
            expect.objectContaining({
                id: 'base',
                thinkingLevels: ['minimal', 'low', 'medium', 'high'],
                defaultThinkingLevel: 'medium',
            }),
        ]);
    });

    it('falls back safely when a stored value is invalid', () => {
        expect(normalizeThinkingLevel('HIGH')).toBe('high');
        expect(normalizeThinkingLevel('untrusted-value')).toBe('medium');
    });
});
