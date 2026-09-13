const STORAGE_KEY = 'remind.activeGuestChatTransfer';
const MAX_TRANSFER_AGE_MS = 24 * 60 * 60 * 1000;
const MAX_TRANSFER_BYTES = 1_000_000;

export type GuestChatTransfer = {
    sessionId: string;
    history: unknown[];
    mindId?: string | null;
    createdAt: number;
};

export function prepareGuestChatTransferHistory(history: unknown[]): unknown[] {
    return history.flatMap((rawMessage) => {
        if (!rawMessage || typeof rawMessage !== 'object') return [];
        const message = rawMessage as { role?: unknown; parts?: unknown };
        if ((message.role !== 'user' && message.role !== 'model') || !Array.isArray(message.parts)) {
            return [];
        }
        const textParts = message.parts.flatMap((rawPart) => {
            if (!rawPart || typeof rawPart !== 'object') return [];
            const text = (rawPart as { text?: unknown }).text;
            return typeof text === 'string' && text ? [{ text }] : [];
        });
        return textParts.length > 0 ? [{ role: message.role, parts: textParts }] : [];
    });
}

export function stageGuestChatTransfer(
    transfer: Omit<GuestChatTransfer, 'createdAt'>
): boolean {
    try {
        const value: GuestChatTransfer = { ...transfer, createdAt: Date.now() };
        const serialized = JSON.stringify(value);
        if (new Blob([serialized]).size > MAX_TRANSFER_BYTES) {
            return false;
        }
        window.sessionStorage.setItem(STORAGE_KEY, serialized);
        return true;
    } catch {
        return false;
    }
}

export function readGuestChatTransfer(): GuestChatTransfer | null {
    try {
        const raw = window.sessionStorage.getItem(STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw) as Partial<GuestChatTransfer>;
        if (
            typeof parsed.sessionId !== 'string'
            || !Array.isArray(parsed.history)
            || parsed.history.length === 0
            || typeof parsed.createdAt !== 'number'
            || Date.now() - parsed.createdAt > MAX_TRANSFER_AGE_MS
        ) {
            clearGuestChatTransfer();
            return null;
        }
        return parsed as GuestChatTransfer;
    } catch {
        clearGuestChatTransfer();
        return null;
    }
}

export function clearGuestChatTransfer(): void {
    try {
        window.sessionStorage.removeItem(STORAGE_KEY);
    } catch {
    }
}

export function hasPendingGuestChatTransfer(sessionId: string): boolean {
    return readGuestChatTransfer()?.sessionId === sessionId;
}
