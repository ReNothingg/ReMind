import { hasEquivalentWidget } from '../../components/Chat/widgetUtils';
import { mergeThinkWidgets } from '../../components/Widgets/thinkBlockUtils';

type Widget = {
    type: string;
    id: string;
    state?: Record<string, unknown>;
    content?: string;
    openTime?: number;
    closeTime?: number;
    [key: string]: unknown;
};

function decode(value: string): string {
    try {
        return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(atob(value), (char) => char.charCodeAt(0)));
    } catch {
        return '';
    }
}

export function parseMessagePresentation(html: string, parts: unknown, messageId: string) {
    const root = document.createElement('div');
    root.innerHTML = html;
    const widgets: Widget[] = [];
    const addJson = (type: string, raw: string, id: string) => {
        try {
            const state: unknown = JSON.parse(raw);
            if (state && typeof state === 'object' && !Array.isArray(state) && !hasEquivalentWidget(widgets, type, state)) {
                widgets.push({ type, id, state: state as Record<string, unknown> });
            }
        } catch {
            return;
        }
    };
    const addThought = (content: string, openTime: number, closeTime: number, id: string) => {
        if (!content || !Number.isFinite(openTime) || !Number.isFinite(closeTime)) return;
        if (!widgets.some((widget) => widget.type === 'think' && widget.openTime === openTime && widget.closeTime === closeTime)) {
            widgets.push({ type: 'think', id, content, openTime, closeTime });
        }
    };
    if (Array.isArray(parts)) {
        parts.forEach((part: unknown, partIndex) => {
            if (!part || typeof part !== 'object' || !('text' in part) || typeof part.text !== 'string') return;
            let index = 0;
            for (const match of part.text.matchAll(/<(beatbox|quiz|spinwheel)>([\s\S]*?)<\/\1>/gi)) {
                if (match[1] && match[2]) addJson(match[1].toLowerCase(), match[2], `${match[1]}-${messageId}-${partIndex}-${index++}`);
            }
            for (const match of part.text.matchAll(/<think(?:\s+data-open="(\d+)")?(?:\s+data-close="(\d+)")?>([\s\S]*?)<\/think>/gi)) {
                addThought((match[3] || '').trim(), Number(match[1] || Date.now()), Number(match[2] || Date.now()), `think-${messageId}-${partIndex}-${index++}`);
            }
        });
    }
    for (const type of ['beatbox', 'quiz', 'spinwheel']) {
        root.querySelectorAll(`.${type}-instance-host`).forEach((host, index) => {
            const encoded = host.getAttribute(`data-${type}-state-b64`);
            addJson(type, encoded ? decode(encoded) : host.getAttribute(`data-${type}-state`) || '', `${type}-${messageId}-${index}`);
            host.remove();
        });
    }
    root.querySelectorAll('.visualize-instance-host').forEach((host, index) => {
        const source = decode(host.getAttribute('data-visualize-source-b64') || '');
        const state = { html: source, title: host.getAttribute('data-visualize-title') || '', mode: host.getAttribute('data-visualize-mode') === 'wide' ? 'wide' : 'normal' };
        if (source && !hasEquivalentWidget(widgets, 'visualize', state)) widgets.push({ type: 'visualize', id: `visualize-${messageId}-${index}`, state });
        host.remove();
    });
    root.querySelectorAll('.think-instance-host').forEach((host, index) => {
        const encoded = host.getAttribute('data-think-content-b64');
        const content = encoded ? decode(encoded) : host.getAttribute('data-think-content') || '';
        addThought(content, Number(host.getAttribute('data-think-open')), Number(host.getAttribute('data-think-close')), `think-${messageId}-${index}`);
        host.remove();
    });
    return { html: root.innerHTML, widgets: mergeThinkWidgets(widgets, `think-${messageId}-merged`) };
}

export function applyMessageWidgetUpdate(widgets: Widget[], update: unknown, messageId: string): Widget[] {
    if (!update || typeof update !== 'object' || !('tag' in update) || !('state' in update)) return widgets;
    const tag = update.tag;
    if (typeof tag !== 'string' || !['beatbox', 'quiz', 'spinwheel', 'visualize'].includes(tag)) return widgets;
    let state: unknown = update.state;
    if (typeof state === 'string') {
        try { state = JSON.parse(state); } catch { return widgets; }
    }
    if (!state || typeof state !== 'object' || Array.isArray(state)) return widgets;
    const nextState = state as Record<string, unknown>;
    const index = widgets.findLastIndex((widget) => widget.type === tag);
    return index < 0
        ? [...widgets, { type: tag, id: `${tag}-${messageId}-stream`, state: nextState }]
        : widgets.map((widget, position) => position === index ? { ...widget, state: nextState } : widget);
}
