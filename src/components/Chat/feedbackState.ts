export type FeedbackRating = 'like' | 'dislike' | null;

export function getFeedbackActionVisibility(rating: FeedbackRating) {
    return {
        like: rating !== 'like',
        dislike: rating !== 'dislike',
    };
}
