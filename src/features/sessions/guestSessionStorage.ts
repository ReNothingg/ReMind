import { ALLOW_GUEST_CHATS_SAVE } from '../../utils/constants';

const GUEST_SESSIONS_KEY = 'guest_chat_history_ids';
export const GUEST_SESSION_TOKENS_KEY = 'guest_chat_tokens';

export type GuestSessionTokenMap = Record<string, string>;

function readStoredJson(key: string): unknown {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? null : JSON.parse(raw);
  } catch {
    return null;
  }
}

function writeStoredJson(key: string, value: string[] | GuestSessionTokenMap): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    console.warn('Guest session storage error');
  }
}

export function readGuestSessionIds(): string[] {
  const stored = readStoredJson(GUEST_SESSIONS_KEY);
  if (!Array.isArray(stored)) return [];
  return [...new Set(stored.filter((id): id is string => typeof id === 'string' && !!id))];
}

export function getGuestSessionTokens(): GuestSessionTokenMap {
  const stored = readStoredJson(GUEST_SESSION_TOKENS_KEY);
  if (!stored || typeof stored !== 'object' || Array.isArray(stored)) return {};
  return Object.fromEntries(
    Object.entries(stored).filter(
      (entry): entry is [string, string] => typeof entry[1] === 'string' && !!entry[1]
    )
  );
}

export function getGuestSessionToken(sessionId: string): string {
  if (!sessionId) return '';
  const tokens = getGuestSessionTokens();
  return Object.hasOwn(tokens, sessionId) ? (tokens[sessionId] ?? '') : '';
}

export function addGuestSession(sessionId: string): void {
  if (!ALLOW_GUEST_CHATS_SAVE || !sessionId) return;
  const previousIds = readGuestSessionIds().filter((id) => id !== sessionId);
  writeStoredJson(GUEST_SESSIONS_KEY, [sessionId, ...previousIds].slice(0, 50));
}

export function storeGuestSessionToken(sessionId: string, token: unknown): void {
  if (!ALLOW_GUEST_CHATS_SAVE || !sessionId || typeof token !== 'string' || !token) return;
  writeStoredJson(GUEST_SESSION_TOKENS_KEY, { ...getGuestSessionTokens(), [sessionId]: token });
}

export function removeGuestSession(sessionId: string): void {
  if (!ALLOW_GUEST_CHATS_SAVE || !sessionId) return;
  const ids = readGuestSessionIds();
  if (ids.includes(sessionId)) {
    writeStoredJson(
      GUEST_SESSIONS_KEY,
      ids.filter((id) => id !== sessionId)
    );
  }

  const tokens = getGuestSessionTokens();
  if (Object.hasOwn(tokens, sessionId)) {
    delete tokens[sessionId];
    writeStoredJson(GUEST_SESSION_TOKENS_KEY, tokens);
  }
}
