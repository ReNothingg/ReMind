export type ContextUsage = {
    input_tokens: number;
    context_limit: number;
    system_tokens: number;
    tool_tokens: number;
    message_tokens: number;
    estimated_breakdown: boolean;
    estimated_total?: boolean;
};

export function readContextUsage(value: unknown): ContextUsage | null {
    if (!value || typeof value !== 'object') return null;
    const data = value as Record<string, unknown>;
    const fields = ['input_tokens', 'context_limit', 'system_tokens', 'tool_tokens', 'message_tokens'] as const;
    if (fields.some(key => typeof data[key] !== 'number' || !Number.isInteger(data[key]) || data[key] < 0 || data[key] > 16_000_000)) return null;
    const result = data as ContextUsage;
    if (result.context_limit <= 0 || result.system_tokens + result.tool_tokens + result.message_tokens !== result.input_tokens) return null;
    return result;
}

type SessionMessage = Record<string, unknown>;

function activeMessage(value: unknown): SessionMessage | null {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const message = value as SessionMessage;
    const index = Number(message.currentVariantIndex ?? message.current_variant_index ?? -1);
    const variant = Array.isArray(message.variants) ? message.variants[index] : null;
    if (!variant || typeof variant !== 'object' || Array.isArray(variant)) return message;
    const selected = variant as SessionMessage;
    return { ...message, ...selected, content: selected.content, parts: selected.parts,
        files: selected.files, images: selected.images,
        contextUsage: selected.contextUsage || selected.context_usage, context_usage: undefined };
}

function messageTokens(message: SessionMessage): number {
    const parts = Array.isArray(message.parts) ? message.parts.filter((part): part is SessionMessage => Boolean(part) && typeof part === 'object' && !Array.isArray(part)) : [];
    let text = typeof message.content === 'string' ? message.content : parts.map(part => typeof part.text === 'string' ? part.text : '').join('\n');
    text = text.replace(/<think(?:\s[^>]*)?>[\s\S]*?<\/think>/gi, '');
    text = text.replace(/<tool_panel data-kind="(?:plan|questions)" data-b64="([A-Za-z0-9+/=]{1,32000})"><\/tool_panel>/g, (_match, encoded: string) => {
        try { return new TextDecoder().decode(Uint8Array.from(atob(encoded), character => character.charCodeAt(0))); }
        catch { return ''; }
    });
    const files = Array.isArray(message.files) && message.files.length ? message.files : parts.filter(part => part.file).map(part => part.file);
    const images = Array.isArray(message.images) && message.images.length ? message.images : parts.filter(part => part.image);
    let count = text ? Math.ceil(new TextEncoder().encode(text).length / 4) + 4 : 0;
    count += images.length * 768;
    for (const item of files) {
        if (!item || typeof item !== 'object') continue;
        const file = (item as SessionMessage).file || item;
        if (!file || typeof file !== 'object') continue;
        const data = file as SessionMessage;
        const bytes = Number(data.size);
        if (Number.isFinite(bytes) && bytes > 0) count += Math.ceil(Math.min(bytes, 8 * 1024 * 1024) / 4);
    }
    return count;
}

export function sessionContextUsage(history: unknown, modelId: string): ContextUsage | null {
    if (!Array.isArray(history)) return null;
    const messages = history.map(activeMessage).filter((message): message is SessionMessage => message !== null && message.is_active !== false);
    let reference: ContextUsage | null = null;
    for (const message of [...messages].reverse()) {
        const messageModel = message.modelId || message.model_id;
        if (messageModel !== modelId) continue;
        reference = readContextUsage(message.contextUsage || message.context_usage);
        if (reference) break;
    }
    if (!reference) return null;
    const seen = new Set<string>();
    const messageCount = messages.reduce((total, message) => {
        const id = typeof message.id === 'string' ? message.id : '';
        if (id && seen.has(id)) return total;
        if (id) seen.add(id);
        return total + messageTokens(message);
    }, 0);
    return {
        ...reference,
        message_tokens: messageCount,
        input_tokens: reference.system_tokens + reference.tool_tokens + messageCount,
        estimated_breakdown: true,
        estimated_total: true,
    };
}
