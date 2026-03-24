import { useCallback, useRef, useState } from 'react';

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

const GUEST_SESSIONS_KEY = 'guest_chat_history_ids';

function readGuestSessionIds(): string[] {
    try {
        const raw = localStorage.getItem(GUEST_SESSIONS_KEY);
        const parsed = raw ? (JSON.parse(raw) as unknown) : [];
        if (!Array.isArray(parsed)) {
            return [];
        }
        return [...new Set(parsed.filter((value): value is string => typeof value === 'string' && value.length > 0))];
    } catch {
        return [];
    }
}

function orderGuestSessions(sessions: SessionSummary[], guestIds: string[]): SessionSummary[] {
    if (guestIds.length === 0) {
        return sessions;
    }

    const byId = new Map(sessions.map((session) => [session.session_id, session]));
    const ordered = guestIds
        .map((id) => byId.get(id))
        .filter((session): session is SessionSummary => Boolean(session));
    const remaining = sessions.filter((session) => !guestIds.includes(session.session_id));

    return [...ordered, ...remaining];
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
    const refreshRequestIdRef = useRef(0);

    const refreshSessions = useCallback(async () => {
        const requestId = refreshRequestIdRef.current + 1;
        refreshRequestIdRef.current = requestId;

        try {
            if (isAuthenticated) {
                const userSessions = await loadAllPages();
                if (refreshRequestIdRef.current === requestId) {
                    setSessions(userSessions);
                }
                return;
            }

            if (!allowGuestChatsSave) {
                if (refreshRequestIdRef.current === requestId) {
                    setSessions([]);
                }
                return;
            }

            try {
                const guestIds = readGuestSessionIds();
                if (guestIds.length === 0) {
                    if (refreshRequestIdRef.current === requestId) {
                        setSessions([]);
                    }
                    return;
                }
                const query = guestIds.join(',');
                const guestSessions = await loadAllPages(query);
                if (refreshRequestIdRef.current === requestId) {
                    setSessions(orderGuestSessions(guestSessions, guestIds));
                }
            } catch (error) {
                console.warn('Failed to load guest sessions', error);
                if (refreshRequestIdRef.current === requestId) {
                    setSessions([]);
                }
            }
        } catch (error) {
            console.error('Failed to load sessions', error);
            if (refreshRequestIdRef.current === requestId) {
                setSessions([]);
            }
        }
    }, [allowGuestChatsSave, isAuthenticated]);

    const removeSession = useCallback((sessionId: string) => {
        setSessions((previousSessions) =>
            previousSessions.filter((session) => session.session_id !== sessionId)
        );
    }, []);

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
        removeSession,
        onSessionRenamed,
    };
}
