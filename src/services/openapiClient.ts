import type { paths } from '../generated/openapi';
import { requestJson, type RequestJsonOptions } from './http';

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
        query,
        ...(headers ? { headers } : {}),
    } satisfies RequestJsonOptions);
}

export function apiGetSessionHistory(sessionId: string, headers?: HeadersInit): Promise<SessionHistoryResponse> {
    return requestJson<SessionHistoryResponse>(`/sessions/${encodeURIComponent(sessionId)}/history`, {
        method: 'GET',
        ...(headers ? { headers } : {}),
    } satisfies RequestJsonOptions);
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
