export type ToolActivity = {
    kind: 'tool';
    id: string;
    name: string;
    status: 'running' | 'completed' | 'failed';
    detail: string;
    durationMs: number;
    error: string;
};

export function decodeToolActivity(encoded: string): ToolActivity | null {
    if (!encoded || encoded.length > 32_000) return null;
    try {
        const normalized = encoded.replace(/-/g, '+').replace(/_/g, '/');
        const binary = window.atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '='));
        const value = JSON.parse(new TextDecoder().decode(Uint8Array.from(binary, (char) => char.charCodeAt(0))));
        if (value?.type !== 'tool_execution' || typeof value.id !== 'string'
            || !/^[a-zA-Z0-9_-]{1,64}$/.test(value.id)
            || typeof value.name !== 'string' || !/^[a-z_]{1,80}$/.test(value.name)
            || !['running', 'completed', 'failed'].includes(value.status)) return null;
        return {
            kind: 'tool', id: value.id, name: value.name, status: value.status,
            detail: typeof value.detail === 'string' ? value.detail.slice(0, 4000) : '',
            error: typeof value.error === 'string' ? value.error.slice(0, 100) : '',
            durationMs: Number.isFinite(value.duration_ms) ? Math.max(0, value.duration_ms) : 0,
        };
    } catch {
        return null;
    }
}
