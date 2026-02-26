import { useCallback, useState } from 'react';

export interface SessionSummary {
    session_id: string;
    title?: string;
    last_updated?: number;
    last_message?: string;
    is_public?: boolean;
    public_id?: string | null;
}

interface ListSessionsResponse {
    ok?: boolean;
    sessions?: SessionSummary[];
    has_more?: boolean;
}

interface UseSessionListOptions {
    isAuthenticated: boolean;
    allowGuestChatsSave: boolean;
}

function getGuestSessionTokens(): Record<string, string> {
    try {
        const raw = localStorage.getItem('guest_chat_tokens');
        const parsed = raw ? (JSON.parse(raw) as unknown) : {};
        if (!parsed || typeof parsed !== 'object') {
            return {};
        }
        return parsed as Record<string, string>;
    } catch {
        return {};
    }
}

async function fetchSessionsPage(idsQuery: string, page: number, pageSize: number): Promise<ListSessionsResponse> {
    const params = new URLSearchParams();
    if (idsQuery) {
        params.set('ids', idsQuery);
    }
    params.set('page', String(page));
    params.set('page_size', String(pageSize));

    const guestTokens = getGuestSessionTokens();
    const headers = Object.keys(guestTokens).length
        ? { 'X-Guest-Tokens': JSON.stringify(guestTokens) }
        : undefined;

    const requestOptions: RequestInit = {
        method: 'GET',
        credentials: 'include',
    };
    if (headers) {
        requestOptions.headers = headers;
    }

    const response = await fetch(`/sessions?${params.toString()}`, requestOptions);
    if (!response.ok) {
        throw new Error(`Failed to list sessions: HTTP ${response.status}`);
    }
    return (await response.json()) as ListSessionsResponse;
}

async function loadAllPages(idsQuery = ''): Promise<SessionSummary[]> {
    const merged: SessionSummary[] = [];
    let page = 1;
    const pageSize = 50;

    while (page <= 20) {
        const data = await fetchSessionsPage(idsQuery, page, pageSize);
        if (Array.isArray(data?.sessions) && data.sessions.length > 0) {
            merged.push(...data.sessions);
        }
        if (!data?.has_more) {
            break;
        }
        page += 1;
    }

    return merged;
}

export function useSessionList({ isAuthenticated, allowGuestChatsSave }: UseSessionListOptions) {
    const [sessions, setSessions] = useState<SessionSummary[]>([]);

    const refreshSessions = useCallback(async () => {
        try {
            if (isAuthenticated) {
                const userSessions = await loadAllPages();
                setSessions(userSessions);
                return;
            }

            if (!allowGuestChatsSave) {
                setSessions([]);
                return;
            }

            try {
                const guestIds = JSON.parse(localStorage.getItem('guest_chat_history_ids') || '[]') as string[];
                if (guestIds.length === 0) {
                    setSessions([]);
                    return;
                }
                const query = guestIds.join(',');
                const guestSessions = await loadAllPages(query);
                setSessions(guestSessions);
            } catch (error) {
                console.warn('Failed to load guest sessions', error);
                setSessions([]);
            }
        } catch (error) {
            console.error('Failed to load sessions', error);
            setSessions([]);
        }
    }, [allowGuestChatsSave, isAuthenticated]);

    const onSessionRenamed = useCallback((sessionId: string, newTitle: string) => {
        setSessions((previousSessions) =>
            previousSessions.map((session) =>
                session.session_id === sessionId ? { ...session, title: newTitle } : session
            )
        );
    }, []);

    return {
        sessions,
        refreshSessions,
        onSessionRenamed,
    };
}
