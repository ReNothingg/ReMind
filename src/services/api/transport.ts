import { SERIOUS_ERROR_KEYPHRASES } from "../../utils/constants";
import {
requestJson,
type RequestJsonOptions
} from "../http";

export const GUEST_SESSION_TOKENS_KEY = 'guest_chat_tokens';

export type GuestSessionTokenMap = Record<string, string>;

export type ApiServiceError = Error & {
    data?: unknown;
    isSerious?: boolean;
    status?: number;
};

export function getGuestSessionToken(sessionId: string): string {
    if (!sessionId) return '';

    try {
        const raw = localStorage.getItem(GUEST_SESSION_TOKENS_KEY);
        const tokens = raw ? (JSON.parse(raw) as GuestSessionTokenMap) : {};
        return tokens[sessionId] || '';
    } catch {
        return '';
    }
}

export function getGuestSessionTokens(): GuestSessionTokenMap {
    try {
        const raw = localStorage.getItem(GUEST_SESSION_TOKENS_KEY);
        const tokens = raw ? (JSON.parse(raw) as unknown) : {};
        return tokens && typeof tokens === 'object' ? (tokens as GuestSessionTokenMap) : {};
    } catch {
        return {};
    }
}

export function toApiServiceError(error: unknown): ApiServiceError {
    return error instanceof Error ? (error as ApiServiceError) : new Error(String(error));
}

export function isGenericHttpMessage(message: string): boolean {
    return /^HTTP error: \d+$/.test(message.trim());
}

export async function fetchApi<TResponse = unknown>(
    endpoint: string,
    options: RequestJsonOptions = {}
): Promise<TResponse> {
    try {
        return await requestJson<TResponse>(endpoint, options);
    } catch (error) {
        const typedError = toApiServiceError(error);
        if (typeof typedError.data === 'string' && typedError.data.trim()) {
            typedError.message = typedError.data;
            typedError.data = { error: typedError.data };
        } else if (isGenericHttpMessage(typedError.message)) {
            const structuredData =
                typedError.data && typeof typedError.data === 'object'
                    ? (typedError.data as { error?: string })
                    : undefined;
            if (structuredData?.error) {
                typedError.message = structuredData.error;
            }
        }
        const normalizedMessage = typedError.message.toLowerCase();

        if (SERIOUS_ERROR_KEYPHRASES.some((phrase) => normalizedMessage.includes(phrase))) {
            typedError.isSerious = true;
        }

        if (
            !(
                normalizedMessage.includes('failed to fetch') ||
                typedError.name === 'AbortError'
            )
        ) {
            const errorDetails = typedError.data ? JSON.stringify(typedError.data) : '';
            console.error(
                `API Error (${endpoint}):`,
                typedError.message,
                errorDetails || typedError
            );
        }

        throw typedError;
    }
}
