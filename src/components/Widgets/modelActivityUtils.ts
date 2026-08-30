export type ModelActivityStatus =
    | 'model_waiting'
    | 'model_responded'
    | 'model_failed';

export type DecodedModelActivity = {
    id: string;
    status: ModelActivityStatus;
    round: number;
};

const VALID_STATUSES = new Set<ModelActivityStatus>([
    'model_waiting',
    'model_responded',
    'model_failed',
]);

export function decodeModelActivity(encoded: string): DecodedModelActivity | null {
    if (!encoded || encoded.length > 4_000) return null;
    try {
        const normalized = encoded.replace(/-/g, '+').replace(/_/g, '/');
        const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
        const binary = window.atob(padded);
        const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
        const payload = JSON.parse(new TextDecoder().decode(bytes));
        const id = String(payload?.id || '').replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 64);
        if (
            payload?.type !== 'model_response'
            || !id
            || !VALID_STATUSES.has(payload.status as ModelActivityStatus)
        ) {
            return null;
        }
        const round = Number(payload.round);
        return {
            id,
            status: payload.status,
            round: Number.isFinite(round) ? Math.max(1, Math.min(11, Math.floor(round))) : 1,
        };
    } catch {
        return null;
    }
}
