export type ImageActivityStatus =
    | 'image_running'
    | 'image_completed'
    | 'image_failed';

export type DecodedImageActivity = {
    id: string;
    status: ImageActivityStatus;
    operation: 'crop' | 'tile';
    purpose: string;
    filename: string;
    imageCount: number;
};

const VALID_STATUSES = new Set<ImageActivityStatus>([
    'image_running',
    'image_completed',
    'image_failed',
]);

export function decodeImageActivity(encoded: string): DecodedImageActivity | null {
    if (!encoded || encoded.length > 16_000) return null;
    try {
        const normalized = encoded.replace(/-/g, '+').replace(/_/g, '/');
        const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
        const binary = window.atob(padded);
        const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
        const payload = JSON.parse(new TextDecoder().decode(bytes));
        const id = String(payload?.id || '').replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 64);
        if (
            payload?.type !== 'image_analysis'
            || !id
            || !VALID_STATUSES.has(payload.status as ImageActivityStatus)
            || !['crop', 'tile'].includes(payload.operation)
        ) {
            return null;
        }
        const imageCount = Number(payload.image_count);
        return {
            id,
            status: payload.status,
            operation: payload.operation,
            purpose: String(payload.purpose || '').replace(/\s+/g, ' ').trim().slice(0, 1_000),
            filename: Array.from(String(payload.filename || ''))
                .filter((character) => character.charCodeAt(0) >= 32)
                .join('')
                .slice(0, 180),
            imageCount: Number.isFinite(imageCount)
                ? Math.max(0, Math.min(9, Math.floor(imageCount)))
                : 0,
        };
    } catch {
        return null;
    }
}
