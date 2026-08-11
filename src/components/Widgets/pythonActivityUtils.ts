export type PythonActivityStatus =
    | 'python_running'
    | 'python_completed'
    | 'python_failed';

export type DecodedPythonActivity = {
    id: string;
    status: PythonActivityStatus;
    code: string;
    purpose: string;
    output: string;
    durationMs: number;
    artifactCount: number;
};

const VALID_PYTHON_STATUSES = new Set<PythonActivityStatus>([
    'python_running',
    'python_completed',
    'python_failed',
]);
const MAX_ENCODED_ACTIVITY_LENGTH = 140_000;
const MAX_CODE_LENGTH = 24_000;
const MAX_PURPOSE_LENGTH = 1_000;
const MAX_OUTPUT_LENGTH = 12_000;

export function decodePythonActivity(encoded: string): DecodedPythonActivity | null {
    if (!encoded || encoded.length > MAX_ENCODED_ACTIVITY_LENGTH) {
        return null;
    }

    try {
        const normalized = encoded.replace(/-/g, '+').replace(/_/g, '/');
        const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
        const binary = window.atob(padded);
        const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
        const payload = JSON.parse(new TextDecoder().decode(bytes));
        const id = String(payload?.id || '').replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 64);
        if (
            payload?.type !== 'python_execution'
            || !id
            || !VALID_PYTHON_STATUSES.has(payload.status as PythonActivityStatus)
        ) {
            return null;
        }

        const durationMs = Number(payload.duration_ms);
        const artifactCount = Number(payload.artifact_count);
        return {
            id,
            status: payload.status,
            code: String(payload.code || '').slice(0, MAX_CODE_LENGTH),
            purpose: String(payload.purpose || '').replace(/\s+/g, ' ').trim().slice(0, MAX_PURPOSE_LENGTH),
            output: String(payload.output || '').slice(0, MAX_OUTPUT_LENGTH),
            durationMs: Number.isFinite(durationMs)
                ? Math.max(0, Math.min(60_000, durationMs))
                : 0,
            artifactCount: Number.isFinite(artifactCount)
                ? Math.max(0, Math.min(10, Math.floor(artifactCount)))
                : 0,
        };
    } catch {
        return null;
    }
}
