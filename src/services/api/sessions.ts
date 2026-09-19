import {
apiGetSessionHistory,
apiListSessions,
type ListSessionsResponse
} from "../openapiClient";
import { fetchApi,getGuestSessionToken,getGuestSessionTokens } from './transport';
import { GuestChatImportResponse,ListSessionsOptions,SessionDeleteResponse,SessionHistoryWithMind,SessionMindResponse,SessionRenameResponse,SessionShareResponse } from './types/common';
import { Mind } from './types/minds';

export const sessionsApi = {
async listSessions(
        options: ListSessionsOptions = ''
    ): Promise<ListSessionsResponse> {
        const guestTokens = getGuestSessionTokens();
        const headers: HeadersInit | undefined = Object.keys(guestTokens).length
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

        if (typeof options === 'string') {
            return apiListSessions(idsQuery ? { ids: idsQuery } : {}, headers);
        }

        const query: { ids?: string; page: number; page_size: number } = {
            page,
            page_size: pageSize,
        };
        if (idsQuery) query.ids = idsQuery;

        return apiListSessions(query, headers);
    },

async getSessionHistory(sessionId: string): Promise<SessionHistoryWithMind> {
        const token = getGuestSessionToken(sessionId);
        const headers: HeadersInit | undefined = token
            ? { Authorization: `Bearer ${token}` }
            : undefined;
        return apiGetSessionHistory(sessionId, headers) as Promise<SessionHistoryWithMind>;
    },

async importActiveGuestChat(payload: {
        sessionId: string;
        history: unknown[];
        mindId?: string | null;
    }): Promise<GuestChatImportResponse> {
        return fetchApi<GuestChatImportResponse>('/sessions/import-active-guest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: payload.sessionId,
                history: payload.history,
                mind_id: payload.mindId || null,
            }),
        });
    },

async selectSessionBranch(sessionId: string, messageId: string): Promise<SessionHistoryWithMind> {
        const token = getGuestSessionToken(sessionId);
        const headers: HeadersInit = {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        };
        return fetchApi<SessionHistoryWithMind>(
            `/sessions/${encodeURIComponent(sessionId)}/branch`,
            {
                method: 'PUT',
                headers,
                body: JSON.stringify({ message_id: messageId }),
            }
        );
    },

async toggleShare(
        sessionId: string,
        isPublic = true
    ): Promise<SessionShareResponse> {
        return fetchApi<SessionShareResponse>(
            `/sessions/${encodeURIComponent(sessionId)}/share`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_public: Boolean(isPublic) }),
            }
        );
    },

async deleteSession(sessionId: string): Promise<SessionDeleteResponse> {
        const token = getGuestSessionToken(sessionId);
        const headers: HeadersInit | undefined = token
            ? { Authorization: `Bearer ${token}` }
            : undefined;
        return fetchApi<SessionDeleteResponse>(`/sessions/${encodeURIComponent(sessionId)}`, {
            method: 'DELETE',
            ...(headers ? { headers } : {}),
        });
    },

async renameSession(
        sessionId: string,
        newTitle: string
    ): Promise<SessionRenameResponse> {
        const token = getGuestSessionToken(sessionId);
        return fetchApi<SessionRenameResponse>(
            `/sessions/${encodeURIComponent(sessionId)}/rename`,
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(token ? { Authorization: `Bearer ${token}` } : {}),
                },
                body: JSON.stringify({ title: newTitle }),
            }
        );
    },

async setSessionMind(sessionId: string, mindId: string | null): Promise<Mind | null> {
        const data = await fetchApi<SessionMindResponse>(
            `/sessions/${encodeURIComponent(sessionId)}/mind`,
            {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mind_id: mindId }),
            }
        );
        return data.mind || null;
    }
};
