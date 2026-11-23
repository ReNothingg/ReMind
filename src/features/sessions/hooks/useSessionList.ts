import { useCallback, useRef, useState } from 'react';
import { sessionsApi } from '../../../services/api/sessions';
import { readGuestSessionIds } from '../guestSessionStorage';

export interface SessionSummary {
  session_id: string;
  title?: string;
  last_updated?: number;
  last_message?: string;
  is_public?: boolean;
  public_id?: string | null;
  source?: 'web' | 'telegram_private' | 'telegram_group' | 'telegram_guest' | 'telegram_inline';
}

interface UseSessionListOptions {
  isAuthenticated: boolean;
  allowGuestChatsSave: boolean;
}

function orderGuestSessions(sessions: SessionSummary[], guestIds: string[]): SessionSummary[] {
  if (guestIds.length === 0) {
    return sessions;
  }

  const byId = new Map(sessions.map((session) => [session.session_id, session]));
  const ordered = guestIds
    .map((id) => byId.get(id))
    .filter((session): session is SessionSummary => Boolean(session));
  const guestIdSet = new Set(guestIds);
  const remaining = sessions.filter((session) => !guestIdSet.has(session.session_id));

  return [...ordered, ...remaining];
}

async function loadAllPages(idsQuery = ''): Promise<SessionSummary[]> {
  const merged: SessionSummary[] = [];
  let page = 1;
  const pageSize = 50;

  while (page <= 20) {
    const data = await sessionsApi.listSessions({ idsQuery, page, pageSize });
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
