import { describe, expect, it } from 'vitest';
import { normalizeHistoryMessage } from './useChat';

describe('chat branch normalization', () => {
    it('restores the selected assistant variant from persisted history', () => {
        const message = normalizeHistoryMessage({
            id: 'a2',
            role: 'model',
            parts: [{ text: 'Second' }],
            variants: [
                { id: 'a1', variant_id: 'a1', role: 'model', parts: [{ text: 'First' }] },
                { id: 'a2', variant_id: 'a2', role: 'model', parts: [{ text: 'Second' }] },
            ],
            current_variant_index: 1,
        });

        expect(message.content).toBe('Second');
        expect(message.currentVariantIndex).toBe(1);
        expect(message.variants.map((variant) => variant.variantId)).toEqual(['a1', 'a2']);
    });

    it('normalizes edited user prompts as navigable variants', () => {
        const message = normalizeHistoryMessage({
            id: 'u2',
            role: 'user',
            parts: [{ text: 'Edited prompt' }],
            variants: [
                { id: 'u1', parts: [{ text: 'Original prompt' }] },
                { id: 'u2', parts: [{ text: 'Edited prompt' }] },
            ],
            current_variant_index: 1,
        });

        expect(message.role).toBe('user');
        expect(message.content).toBe('Edited prompt');
        expect(message.variants[0].content).toBe('Original prompt');
    });

    it('restores interrupted state from the selected persisted variant', () => {
        const message = normalizeHistoryMessage({
            id: 'a2',
            role: 'model',
            parts: [{ text: 'Partial answer' }],
            variants: [
                { id: 'a1', parts: [{ text: 'Complete answer' }], delivery_status: 'complete' },
                { id: 'a2', parts: [{ text: 'Partial answer' }], delivery_status: 'interrupted' },
            ],
            current_variant_index: 1,
        });

        expect(message.deliveryState).toBe('interrupted');
    });
});
