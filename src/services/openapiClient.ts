import { API_BASE_URL } from '../utils/constants';
import type { paths } from '../generated/openapi';

const CSRF_COOKIE_KEY = 'csrf_token';
const CSRF_HEADER_KEY = 'X-CSRF-Token';
const SAFE_METHODS = ['GET', 'HEAD', 'OPTIONS'];

export class ApiClientError extends Error {
    status?: number;
    data?: unknown;
}

function getCookie(name: string): string {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
        return parts.pop()?.split(';').shift() || '';
    }
    return '';
}

function withCsrfHeaders(method: string, headers: Headers): Headers {
    if (SAFE_METHODS.includes(method.toUpperCase())) {
        return headers;
    }
    if (headers.has(CSRF_HEADER_KEY)) {
        return headers;
    }
    const token = getCookie(CSRF_COOKIE_KEY);
    if (token) {
        headers.set(CSRF_HEADER_KEY, token);
    }
    return headers;
}

function buildQueryString(query?: Record<string, unknown>): string {
    if (!query) return '';
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
        if (value === undefined || value === null || value === '') return;
        params.set(key, String(value));
    });
    const serialized = params.toString();
    return serialized ? `?${serialized}` : '';
}

type RequestInitExt = RequestInit & {
    query?: Record<string, unknown>;
};

async function requestJson<TResponse>(path: string, options: RequestInitExt = {}): Promise<TResponse> {
    const baseURL = API_BASE_URL || '';
    const method = (options.method || 'GET').toUpperCase();
    const headers = withCsrfHeaders(method, new Headers(options.headers || {}));
    const queryString = buildQueryString(options.query);
    const url = `${baseURL}${path}${queryString}`;

    const response = await fetch(url, {
        ...options,
        method,
        headers,
        credentials: options.credentials || 'include',
    });

    if (!response.ok) {
        let data: unknown = null;
        try {
            data = await response.json();
        } catch (_error) {
            try {
                data = await response.text();
            } catch (_innerError) {
                data = null;
            }
        }
        const err = new ApiClientError(
            (data as { error?: string })?.error || `HTTP error: ${response.status}`
        );
        err.status = response.status;
        err.data = data;
        throw err;
    }

    if (response.status === 204) {
        return null as TResponse;
    }

    return response.json() as Promise<TResponse>;
}

export type AuthCheckResponse = paths['/api/auth/check']['get']['responses']['200']['content']['application/json'];
export type AuthLoginRequest = paths['/api/auth/login']['post']['requestBody']['content']['application/json'];
export type AuthLoginResponse = paths['/api/auth/login']['post']['responses']['200']['content']['application/json'];

export type ListSessionsQuery = paths['/sessions']['get']['parameters']['query'];
export type ListSessionsResponse = paths['/sessions']['get']['responses']['200']['content']['application/json'];

export type SessionHistoryResponse = paths['/sessions/{session_id}/history']['get']['responses']['200']['content']['application/json'];
export type TranslateRequest = paths['/translate']['post']['requestBody']['content']['application/json'];
export type TranslateResponse = paths['/translate']['post']['responses']['200']['content']['application/json'];
export type SynthesizeRequest = paths['/synthesize']['post']['requestBody']['content']['application/json'];
export type SynthesizeResponse = paths['/synthesize']['post']['responses']['200']['content']['application/json'];

export function apiAuthCheck(): Promise<AuthCheckResponse> {
    return requestJson<AuthCheckResponse>('/api/auth/check', { method: 'GET' });
}

export function apiAuthLogin(payload: AuthLoginRequest): Promise<AuthLoginResponse> {
    return requestJson<AuthLoginResponse>('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
}

export function apiListSessions(query: ListSessionsQuery = {}, headers?: HeadersInit): Promise<ListSessionsResponse> {
    return requestJson<ListSessionsResponse>('/sessions', {
        method: 'GET',
        headers,
        query,
    });
}

export function apiGetSessionHistory(sessionId: string, headers?: HeadersInit): Promise<SessionHistoryResponse> {
    return requestJson<SessionHistoryResponse>(`/sessions/${encodeURIComponent(sessionId)}/history`, {
        method: 'GET',
        headers,
    });
}

export function apiTranslate(payload: TranslateRequest): Promise<TranslateResponse> {
    return requestJson<TranslateResponse>('/translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
}

export function apiSynthesize(payload: SynthesizeRequest): Promise<SynthesizeResponse> {
    return requestJson<SynthesizeResponse>('/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
}
