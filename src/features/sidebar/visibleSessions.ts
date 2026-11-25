import type { SessionSummary } from '../sessions/hooks/useSessionList';

export const sessionRowsPerPage = 5;
const attentionLimit = 50;

export function visibleSessionRows<T extends SessionSummary>(
  sessions: readonly T[],
  requested: number,
  currentSessionId: string | null,
  requiresAttention: (id: string) => boolean
) {
  let required = requested;
  let count = 0;
  for (const session of sessions) {
    if (session.title || session.last_message) count += 1;
    if (session.session_id === currentSessionId || (count <= attentionLimit && requiresAttention(session.session_id))) {
      required = Math.max(required, count);
    }
  }

  count = 0;
  const rows = sessions.filter((session) => {
    if (!session.title && !session.last_message) return true;
    count += 1;
    return count <= required;
  });
  return { rows, hiddenCount: sessions.length - rows.length, watermark: required };
}
