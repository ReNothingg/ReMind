import { extractApiErrorMessage } from '../../services/http';

const HTML_ERROR_PATTERN = /<\/?[a-z][\s\S]*>/i;
const GENERIC_HTTP_ERROR_PATTERN = /^HTTP error:\s*\d+$/i;

function getErrorStatus(error: unknown): number | undefined {
    if (!error || typeof error !== 'object') {
        return undefined;
    }

    const status = (error as { status?: unknown }).status;
    return typeof status === 'number' ? status : undefined;
}

type MindErrorMessages = {
    authRequired: string;
    accessDenied: string;
    notFound: string;
    rateLimited: string;
};

export function getMindErrorMessage(
    error: unknown,
    fallback: string,
    messages?: MindErrorMessages
): string {
    const status = getErrorStatus(error);
    const message = extractApiErrorMessage(error, fallback).trim();

    if (
        message &&
        !GENERIC_HTTP_ERROR_PATTERN.test(message) &&
        !HTML_ERROR_PATTERN.test(message) &&
        message.length <= 400
    ) {
        return message;
    }

    if (status === 401) {
        return messages?.authRequired || 'Sign in to perform this action.';
    }

    if (status === 403) {
        return messages?.accessDenied || 'You do not have access to this mind.';
    }

    if (status === 404) {
        return messages?.notFound || 'The minds service is unavailable or the mind was not found.';
    }

    if (status === 429) {
        return messages?.rateLimited || 'Too many requests. Wait a bit and try again.';
    }
    return fallback;
}
