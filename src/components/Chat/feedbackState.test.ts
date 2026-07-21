import { describe, expect, it } from 'vitest';
import { getFeedbackActionVisibility } from './feedbackState';

describe('feedback action visibility', () => {
    it('shows both actions before the response is rated', () => {
        expect(getFeedbackActionVisibility(null)).toEqual({
            like: true,
            dislike: true,
        });
    });

    it('keeps only dislike available after a like', () => {
        expect(getFeedbackActionVisibility('like')).toEqual({
            like: false,
            dislike: true,
        });
    });

    it('keeps only like available after a dislike', () => {
        expect(getFeedbackActionVisibility('dislike')).toEqual({
            like: true,
            dislike: false,
        });
    });
});
