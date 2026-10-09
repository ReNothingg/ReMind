import i18n from 'i18next';
import {
buildApiUrl,
withCsrfHeaders
} from "../http";
import { ApiServiceError,fetchApi,getGuestSessionToken,toApiServiceError } from './transport';
import { ChatCallbacks,ChatStreamResult } from './types/chat';
import { AIResponseFeedbackPayload } from './types/common';

export const CHAT_STREAM_IDLE_TIMEOUT_MS = 135_000;

const CHAT_ERROR_KEYS: Record<string, string> = {
    provider_access_denied: 'chat.providerErrors.accessDenied',
    provider_not_configured: 'chat.providerErrors.notConfigured',
    provider_model_unavailable: 'chat.providerErrors.modelUnavailable',
    provider_rate_limited: 'chat.providerErrors.rateLimited',
    provider_unavailable: 'chat.providerErrors.unavailable',
    chat_variant_limit_reached: 'chat.variantLimitReached',
    message_id_conflict: 'chat.versionConflict',
};

export function getChatErrorCode(error: Error): string {
    const data = (error as ApiServiceError).data as { error?: string | { code?: string } } | undefined;
    return typeof data?.error === 'string' ? data.error : data?.error?.code || '';
}

export function getChatErrorMessage(error: Error): string {
    const code = getChatErrorCode(error);
    const key = Object.hasOwn(CHAT_ERROR_KEYS, code) ? CHAT_ERROR_KEYS[code] : undefined;
    return i18n.t(key || 'chat.generationFailed');
}

class ChatStreamError extends Error {
    data: { error: { code: string } };
    status?: number;

    constructor(error: unknown) {
        super('stream_failed');
        const details = error && typeof error === 'object'
            ? error as { code?: unknown; status?: unknown } : undefined;
        const code = typeof error === 'string' ? error
            : typeof details?.code === 'string' ? details.code : 'stream_failed';
        this.data = { error: { code } };
        if (typeof details?.status === 'number') this.status = details.status;
        this.message = getChatErrorMessage(this);
    }
}

export type ChatStreamReader = {
    cancel?: (reason?: unknown) => Promise<void>;
    read: () => Promise<ReadableStreamReadResult<Uint8Array>>;
};

export async function readChatStreamChunk(
    reader: ChatStreamReader,
    timeoutMs = CHAT_STREAM_IDLE_TIMEOUT_MS,
): Promise<ReadableStreamReadResult<Uint8Array>> {
    let timeoutId: ReturnType<typeof globalThis.setTimeout> | undefined;
    const timeoutError = new Error('chat_stream_idle_timeout');
    try {
        return await Promise.race([
            reader.read(),
            new Promise<never>((_resolve, reject) => {
                timeoutId = globalThis.setTimeout(() => {
                    void reader.cancel?.(timeoutError).catch(() => undefined);
                    reject(timeoutError);
                }, Math.max(1, timeoutMs));
            }),
        ]);
    } finally {
        if (timeoutId !== undefined) {
            globalThis.clearTimeout(timeoutId);
        }
    }
}

export const chatApi = {
async chat(
        formData: FormData,
        signal?: AbortSignal,
        callbacks: ChatCallbacks = {}
    ): Promise<void> {
        const { onPart, onComplete, onError, onWidgetUpdate, onCanvasUpdate, onOpen } = callbacks;

        try {
            const sessionId = String(formData.get('session_id') || '');
            const guestToken = getGuestSessionToken(sessionId);
            const response = await fetch(
                buildApiUrl('/chat'),
                withCsrfHeaders({
                    method: 'POST',
                    body: formData,
                    credentials: 'include',
                    ...(guestToken ? { headers: { Authorization: `Bearer ${guestToken}` } } : {}),
                    ...(signal ? { signal } : {}),
                })
            );

            if (!response.ok) {
                const fallbackMessage = `HTTP error! status: ${response.status}`;
                const errorData = (await response
                    .json()
                    .catch(() => ({ error: fallbackMessage }))) as {
                        error?: string | { message?: string; code?: string };
                    };
                const apiMessage = typeof errorData.error === 'string'
                    ? errorData.error
                    : errorData.error?.message;
                const errorCode = typeof errorData.error === 'object' ? errorData.error?.code : undefined;
                const localizedMessage = errorCode === 'tool_unavailable' || errorCode === 'invalid_tool_selection'
                    ? i18n.t('composer.tools.unavailable') : apiMessage;
                const chatError = new Error(localizedMessage || fallbackMessage) as ApiServiceError;
                chatError.status = response.status;
                chatError.data = errorData;
                throw chatError;
            }

            onOpen?.({
                requestId: response.headers.get('X-Chat-Request-Id') || '',
                sessionToken: response.headers.get('X-Chat-Session-Token') || '',
            });

            const contentType = response.headers.get('content-type');
            if (contentType?.includes('text/event-stream')) {
                const reader = response.body?.getReader();
                if (!reader) {
                    throw new Error('Streaming response body is missing.');
                }

                const decoder = new TextDecoder();
                let buffer = '';
                let finalData: ChatStreamResult = {};
                let receivedTerminalEvent = false;

                while (true) {
                    const { value, done } = await readChatStreamChunk(reader);
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const parts = buffer.split('\n\n');
                    buffer = parts.pop() ?? '';

                    for (const part of parts) {
                        if (!part.startsWith('data: ')) {
                            continue;
                        }

                        try {
                            const data = JSON.parse(part.substring(6)) as ChatStreamResult;

                            if (data.error) {
                                await reader.cancel().catch(() => undefined);
                                throw new ChatStreamError(data.error);
                            }

                            if (data.widget_update && onWidgetUpdate) {
                                try {
                                    onWidgetUpdate(data.widget_update);
                                } catch (widgetError) {
                                    console.warn('onWidgetUpdate handler error', widgetError);
                                }

                                finalData = { ...finalData, widget_update: data.widget_update };
                                continue;
                            }

                            if (data.canvas_update && onCanvasUpdate) {
                                try {
                                    onCanvasUpdate(data.canvas_update);
                                } catch (canvasError) {
                                    console.warn('onCanvasUpdate handler error', canvasError);
                                }

                                finalData = {
                                    ...finalData,
                                    canvas_update: data.canvas_update,
                                };
                                if (data.canvas_update.textdoc !== undefined) {
                                    finalData.canvas_textdoc = data.canvas_update.textdoc;
                                }
                                continue;
                            }

                            const shouldEmitPart = [
                                'reply_part',
                                'status',
                                'images',
                                'sources',
                                'thinkingTime',
                                'thinking_update',
                                'canvas_textdoc',
                                'canvas_updates',
                            ].some((key) => key in data);

                            if (shouldEmitPart) {
                                onPart?.(data);
                            }

                            if ('reply' in data || data.end_of_stream) {
                                finalData = { ...finalData, ...data };
                                receivedTerminalEvent = true;
                            }

                            if ('sources' in data) finalData.sources = data.sources;
                            if ('images' in data) finalData.images = data.images;
                            if ('thinkingTime' in data) {
                                finalData.thinkingTime = data.thinkingTime;
                            }
                            if ('status' in data) finalData.status = data.status;
                            if ('sessionId' in data) finalData.sessionId = data.sessionId;
                            if ('sessionSlug' in data) {
                                finalData.sessionSlug = data.sessionSlug;
                            }
                            if ('canvas_textdoc' in data) {
                                finalData.canvas_textdoc = data.canvas_textdoc;
                            }
                            if ('canvas_updates' in data) {
                                finalData.canvas_updates = data.canvas_updates;
                            }
                            if ('canvas_update' in data) {
                                finalData.canvas_update = data.canvas_update;
                                if (data.canvas_update?.textdoc !== undefined) {
                                    finalData.canvas_textdoc = data.canvas_update.textdoc;
                                }
                            }

                            const knownKeys = new Set([
                                'reply',
                                'reply_part',
                                'end_of_stream',
                                'images',
                                'sources',
                                'thinkingTime',
                                'thinking_update',
                                'status',
                                'aborted',
                                'sessionId',
                                'sessionSlug',
                                'widget_update',
                                'canvas_update',
                                'canvas_updates',
                                'canvas_textdoc',
                            ]);

                            Object.keys(data).forEach((key) => {
                                if (!knownKeys.has(key)) {
                                    finalData[key] = data[key];
                                }
                            });
                        } catch (chunkError) {
                            if (chunkError instanceof ChatStreamError) throw chunkError;
                            console.error(
                                'Error parsing stream data chunk:',
                                chunkError,
                                'Chunk:',
                                part.substring(6)
                            );
                        }
                    }
                }

                if (!receivedTerminalEvent) {
                    throw new Error('stream_interrupted');
                }

                onComplete?.(finalData);
                return;
            }

            const data = (await response.json()) as ChatStreamResult;
            onComplete?.(data);
        } catch (error) {
            const typedError = toApiServiceError(error);

            if (typedError.name !== 'AbortError') {
                console.error('API Chat Error:', typedError);
                onError?.(typedError);
            } else {
                onComplete?.({ aborted: true });
            }
        }
    },

async submitAIResponseFeedback(
        payload: AIResponseFeedbackPayload
    ): Promise<{ feedback?: { rating?: string; service_improvement_opt_in?: boolean } }> {
        return fetchApi('/api/feedback/ai-response', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
    }
};
