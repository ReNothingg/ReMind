import { decodeSearchActivity, decodeThoughtEntities, type DecodedSearchActivity } from './searchActivityUtils';
import { decodePythonActivity, type DecodedPythonActivity } from './pythonActivityUtils';
import { decodeImageActivity, type DecodedImageActivity } from './imageActivityUtils';
import { decodeModelActivity, type DecodedModelActivity } from './modelActivityUtils';
import { decodeToolActivity, type ToolActivity } from './toolActivityUtils';

export type ThoughtSection = { kind: 'thought'; body: string };
export type SearchActivity = DecodedSearchActivity & { kind: 'search' };
export type PythonActivity = DecodedPythonActivity & { kind: 'python' };
export type ImageActivity = DecodedImageActivity & { kind: 'image' };
export type ModelActivity = DecodedModelActivity & { kind: 'model' };
export type ThoughtTimelineItem = ThoughtSection | SearchActivity | PythonActivity | ImageActivity | ModelActivity | ToolActivity;

export function parseThoughtTimeline(value: string): ThoughtTimelineItem[] {
    const text = decodeThoughtEntities(String(value || '')).replace(/<(?:search|python|image|model|tool)_activity\b(?![\s\S]*?<\/(?:search|python|image|model|tool)_activity>)[\s\S]*$/, '').trim();
    if (!text) {
        return [];
    }
    const markerRegex = /<search_activity\s+data-b64="([A-Za-z0-9_+/=-]+)"\s*><\/search_activity>|<python_activity\s+data-b64="([A-Za-z0-9_+/=-]+)"\s*><\/python_activity>|<image_activity\s+data-b64="([A-Za-z0-9_+/=-]+)"\s*><\/image_activity>|<model_activity\s+data-b64="([A-Za-z0-9_+/=-]+)"\s*><\/model_activity>|<tool_activity\s+data-b64="([A-Za-z0-9_+/=-]+)"\s*><\/tool_activity>/g;
    const items: ThoughtTimelineItem[] = [];
    let cursor = 0;
    let match: RegExpExecArray | null;

    const flushThought = (body: string) => {
        const normalizedBody = body.trim();
        if (normalizedBody) items.push({ kind: 'thought', body: normalizedBody });
    };

    while ((match = markerRegex.exec(text)) !== null) {
        flushThought(text.slice(cursor, match.index));
        if (match[1]) {
            const activity = decodeSearchActivity(match[1]);
            if (activity) {
                items.push({ kind: 'search', ...activity });
            }
        } else if (match[2]) {
            const activity = decodePythonActivity(match[2]);
            if (activity) {
                items.push({ kind: 'python', ...activity });
            }
        } else if (match[3]) {
            const activity = decodeImageActivity(match[3]);
            if (activity) {
                items.push({ kind: 'image', ...activity });
            }
        } else if (match[4]) {
            const activity = decodeModelActivity(match[4]);
            if (activity) {
                items.push({ kind: 'model', ...activity });
            }
        } else if (match[5]) {
            const activity = decodeToolActivity(match[5]);
            if (activity) items.push(activity);
        }
        cursor = match.index + match[0].length;
    }
    flushThought(text.slice(cursor));
    const mergedItems: ThoughtTimelineItem[] = [];
    const pythonIndexes = new Map<string, number>();
    const imageIndexes = new Map<string, number>();
    const modelIndexes = new Map<string, number>();
    const toolIndexes = new Map<string, number>();
    items.forEach((item) => {
        if (item.kind === 'tool') {
            const existingIndex = toolIndexes.get(item.id);
            if (existingIndex === undefined) {
                toolIndexes.set(item.id, mergedItems.length);
                mergedItems.push(item);
            } else {
                mergedItems[existingIndex] = item;
            }
            return;
        }
        if (item.kind === 'model') {
            const existingIndex = modelIndexes.get(item.id);
            if (existingIndex === undefined) {
                modelIndexes.set(item.id, mergedItems.length);
                mergedItems.push(item);
            } else {
                mergedItems[existingIndex] = item;
            }
            return;
        }
        if (item.kind === 'image') {
            const existingIndex = imageIndexes.get(item.id);
            if (existingIndex === undefined) {
                imageIndexes.set(item.id, mergedItems.length);
                mergedItems.push(item);
            } else {
                const existing = mergedItems[existingIndex];
                if (existing.kind === 'image') {
                    mergedItems[existingIndex] = {
                        ...existing,
                        ...item,
                        purpose: item.purpose || existing.purpose,
                        filename: item.filename || existing.filename,
                    };
                }
            }
            return;
        }
        if (item.kind !== 'python') {
            mergedItems.push(item);
            return;
        }
        const existingIndex = pythonIndexes.get(item.id);
        if (existingIndex === undefined) {
            pythonIndexes.set(item.id, mergedItems.length);
            mergedItems.push(item);
            return;
        }
        const existing = mergedItems[existingIndex];
        if (existing.kind === 'python') {
            mergedItems[existingIndex] = {
                ...existing,
                ...item,
                code: item.code || existing.code,
                codeTruncated: item.code ? item.codeTruncated : existing.codeTruncated,
                purpose: item.purpose || existing.purpose,
            };
        }
    });
    const terminalSearchQueries = new Set(mergedItems
        .filter((item): item is SearchActivity => (
            item.kind === 'search'
            && ['web_search_done', 'web_search_no_results', 'web_search_failed'].includes(item.status)
        ))
        .map((item) => item.query.trim()));
    const latestPendingSearchIndex = new Map<string, number>();
    mergedItems.forEach((item, index) => {
        if (
            item.kind === 'search'
            && ['web_search_started', 'web_search_fetching'].includes(item.status)
            && !terminalSearchQueries.has(item.query.trim())
        ) {
            latestPendingSearchIndex.set(item.query.trim(), index);
        }
    });
    return mergedItems.filter((item, index) => {
        if (
            item.kind !== 'search'
            || !['web_search_started', 'web_search_fetching'].includes(item.status)
        ) {
            return true;
        }
        const query = item.query.trim();
        return !terminalSearchQueries.has(query) && latestPendingSearchIndex.get(query) === index;
    });
}
