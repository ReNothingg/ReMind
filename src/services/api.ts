import { API_BASE_URL } from '../utils/constants';
import { SERIOUS_ERROR_KEYPHRASES } from '../utils/constants';
import {
    apiGetSessionHistory,
    apiListSessions,
    apiSynthesize,
    apiTranslate
} from './openapiClient';

const CSRF_COOKIE_KEY = 'csrf_token';
const CSRF_HEADER_KEY = 'X-CSRF-Token';
const GUEST_SESSION_TOKENS_KEY = 'guest_chat_tokens';
const SAFE_METHODS = ['GET', 'HEAD', 'OPTIONS'];

function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
}

export function getCsrfToken() {
    return getCookie(CSRF_COOKIE_KEY);
}

function getGuestSessionToken(sessionId) {
    if (!sessionId) return '';
    try {
        const raw = localStorage.getItem(GUEST_SESSION_TOKENS_KEY);
        const tokens = raw ? JSON.parse(raw) : {};
        return tokens[sessionId] || '';
    } catch (e) {
        return '';
    }
}

function getGuestSessionTokens() {
    try {
        const raw = localStorage.getItem(GUEST_SESSION_TOKENS_KEY);
        const tokens = raw ? JSON.parse(raw) : {};
        return tokens && typeof tokens === 'object' ? tokens : {};
    } catch (e) {
        return {};
    }
}

function withCsrfHeaders(options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    const headers = new Headers(options.headers || {});
    if (!SAFE_METHODS.includes(method)) {
        const token = getCsrfToken();
        if (token && !headers.has(CSRF_HEADER_KEY)) {
            headers.set(CSRF_HEADER_KEY, token);
        }
    }
    return { ...options, headers };
}

export const apiService = {
    baseURL: API_BASE_URL || '',

    async _fetch(endpoint, options = {}) {
        try {
            const url = this.baseURL ? `${this.baseURL}${endpoint}` : endpoint;
            const requestOptions = withCsrfHeaders({
                credentials: options.credentials || 'include',
                ...options
            });
            const response = await fetch(url, requestOptions);
            if (!response.ok) {
                let errorData = { error: `HTTP error! status: ${response.status} ${response.statusText}`, status: response.status };
                try {
                    const errorJson = await response.json();
                    errorData = { ...errorData, ...errorJson };
                } catch (e) {
                    try {
                        const errorText = await response.text();
                        if (errorText) errorData.error = errorText;
                    } catch (_textError) {
                    }
                }
                const err = new Error(errorData.error || `HTTP error! status: ${response.status}`);
                err.status = response.status;
                err.data = errorData;
                throw err;
            }
            return response.status === 204 ? null : response.json();
        } catch (error) {
            const emsg = (error?.message || '').toLowerCase();
            if (SERIOUS_ERROR_KEYPHRASES.some(phrase => emsg.includes(phrase))) {
                error.isSerious = true;
            }
            if (!(emsg.includes("failed to fetch") || error.name === 'AbortError')) {
                const errorMessage = error?.message || String(error);
                const errorDetails = error?.data ? JSON.stringify(error.data) : '';
                console.error(`API Error (${endpoint}):`, errorMessage, errorDetails || error);
            }
            throw error;
        }
    },
    async chat(formData, signal, callbacks = {}) {
        const { onPart, onComplete, onError, onWidgetUpdate } = callbacks;
        try {
            const url = this.baseURL ? `${this.baseURL}/chat` : '/chat';
            const response = await fetch(url, withCsrfHeaders({
                method: 'POST',
                body: formData,
                signal,
                credentials: 'include'
            }));

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ error: `HTTP error! status: ${response.status}` }));
                throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
            }

            const contentType = response.headers.get("content-type");
            if (contentType?.includes("text/event-stream")) {
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                let finalData = {};

                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const parts = buffer.split('\n\n');
                    buffer = parts.pop();

                    for (const part of parts) {
                        if (part.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(part.substring(6));
                                if (data.widget_update && onWidgetUpdate) {
                                    try {
                                        onWidgetUpdate(data.widget_update);
                                    } catch (e) {
                                        console.warn('onWidgetUpdate handler error', e);
                                    }
                                    finalData = { ...finalData, widget_update: data.widget_update };
                                    continue;
                                }

                                if (data.reply || data.end_of_stream) {
                                    finalData = { ...finalData, ...data };
                                }
                                if (data.reply_part) {
                                    if (onPart) onPart(data);
                                    if (data.sources) finalData.sources = data.sources;
                                    if (data.images) finalData.images = data.images;
                                    if (data.thinkingTime) finalData.thinkingTime = data.thinkingTime;
                                }
                                if (data.sessionId) finalData.sessionId = data.sessionId;
                                if (data.sessionSlug) finalData.sessionSlug = data.sessionSlug;
                                const known = ['reply', 'reply_part', 'end_of_stream', 'images', 'sources', 'thinkingTime', 'status', 'aborted', 'sessionId', 'sessionSlug'];
                                Object.keys(data).forEach(k => {
                                    if (!known.includes(k)) {
                                        finalData[k] = data[k];
                                    } else if (k === 'sessionId' || k === 'sessionSlug') {
                                        finalData[k] = data[k];
                                    }
                                });
                            } catch (e) {
                                console.error("Error parsing stream data chunk:", e, "Chunk:", part.substring(6));
                            }
                        }
                    }
                }
                if (onComplete) onComplete(finalData);
            } else {
                const data = await response.json();
                if (onComplete) onComplete(data);
            }
        } catch (error) {
            if (error.name !== 'AbortError') {
                console.error("API Chat Error:", error);
                if (onError) onError(error);
            } else {
                if (onComplete) onComplete({ aborted: true });
            }
        }
    },

    async listSessions(options: string | { idsQuery?: string; page?: number; pageSize?: number } = '') {
        const guestTokens = getGuestSessionTokens();
        const headers = Object.keys(guestTokens).length
            ? { 'X-Guest-Tokens': JSON.stringify(guestTokens) }
            : undefined;

        let idsQuery = '';
        let page = 1;
        let pageSize = 50;

        if (typeof options === 'string') {
            idsQuery = options;
        } else if (options && typeof options === 'object') {
            idsQuery = options.idsQuery || '';
            page = Number(options.page || 1);
            pageSize = Number(options.pageSize || 50);
        }

        return apiListSessions(
            {
                ids: idsQuery || undefined,
                page,
                page_size: pageSize
            },
            headers
        );
    },

    async getSessionHistory(sessionId) {
        const token = getGuestSessionToken(sessionId);
        const headers = token ? { Authorization: `Bearer ${token}` } : undefined;
        return apiGetSessionHistory(sessionId, headers);
    },

    async toggleShare(sessionId, isPublic = true) {
        return this._fetch(`/sessions/${encodeURIComponent(sessionId)}/share`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_public: Boolean(isPublic) })
        });
    },

    async deleteSession(sessionId) {
        const token = getGuestSessionToken(sessionId);
        const headers = token ? { Authorization: `Bearer ${token}` } : undefined;
        return this._fetch(`/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE', headers });
    },

    async renameSession(sessionId, newTitle) {
        return this._fetch(`/sessions/${encodeURIComponent(sessionId)}/rename`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: newTitle })
        });
    },

    async canvasAction(actionData, signal) {
        return this._fetch('/canvas-action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(actionData),
            signal
        });
    },

    async translate(text, targetLang) {
        try {
            return await apiTranslate({ text, target_lang: targetLang });
        } catch (error) {
            console.warn('Primary translation API failed, trying fallback:', error);
            try {
                return await this._translateWithFallback(text, targetLang);
            } catch (fallbackError) {
                console.error('Fallback translation also failed:', fallbackError);
                throw error;
            }
        }
    },

    _translateWithFallback(text, targetLang) {
        const fallbackTranslations = {
            'en': { 'ru': { 'hello': 'привет', 'world': 'мир' } },
            'ru': { 'en': { 'привет': 'hello', 'мир': 'world' } }
        };
        const sourceLang = /[а-яё]/i.test(text) ? 'ru' : 'en';
        const translations = fallbackTranslations[sourceLang]?.[targetLang];
        if (translations) {
            let translatedText = text;
            for (const [original, translated] of Object.entries(translations)) {
                translatedText = translatedText.replace(new RegExp(`\\b${original}\\b`, 'gi'), translated);
            }
            return Promise.resolve({
                translated_text: translatedText,
                source_lang: sourceLang,
                target_lang: targetLang,
                fallback: true
            });
        }
        return Promise.reject(new Error('Fallback translation not available'));
    },

    async synthesize(text) {
        return apiSynthesize({ text });
    },

    async getLinkMetadata(url) {
        return this._fetch('/get-link-metadata', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
    },

    async exportPrivacyData() {
        return this._fetch('/api/privacy/export', { method: 'GET' });
    },

    async deletePrivacyData(deleteAccount = false) {
        return this._fetch('/api/privacy/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delete_account: Boolean(deleteAccount) })
        });
    },

    async fetchTextResource(filePath) {
        try {
            const response = await fetch(filePath, { cache: "no-store" });
            if (!response.ok) throw new Error(`Network response was not ok for ${filePath}`);
            const textContent = await response.text();
            return textContent.split('\n').filter(phrase => phrase.trim() !== '');
        } catch (error) {
            console.warn(`Failed to load text resource ${filePath}:`, error.message);
            return [];
        }
    }
};
