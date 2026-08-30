import { Fragment, type ReactNode, useEffect, useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import Prism from 'prismjs';
import 'prismjs/components/prism-python';
import { cn } from '../../utils/cn';
import WebSourcesPanel from './WebSourcesPanel';
import {
    decodeSearchActivity,
    decodeThoughtEntities,
    type DecodedSearchActivity,
} from './searchActivityUtils';
import {
    decodePythonActivity,
    type DecodedPythonActivity,
} from './pythonActivityUtils';
import {
    decodeImageActivity,
    type DecodedImageActivity,
} from './imageActivityUtils';
import {
    decodeModelActivity,
    type DecodedModelActivity,
} from './modelActivityUtils';

type ThoughtSection = {
    kind: 'thought';
    heading?: string;
    body: string;
};

type SearchActivity = DecodedSearchActivity & {
    kind: 'search';
};

type PythonActivity = DecodedPythonActivity & {
    kind: 'python';
};

type ImageActivity = DecodedImageActivity & {
    kind: 'image';
};

type ModelActivity = DecodedModelActivity & {
    kind: 'model';
};

type ThoughtTimelineItem = ThoughtSection | SearchActivity | PythonActivity | ImageActivity | ModelActivity;

type ThinkBlockProps = {
    content?: string;
    openTime?: number;
    closeTime?: number;
    isStreaming?: boolean;
};

type PythonSyntaxToken = string | {
    type: string;
    alias?: string | string[];
    content: PythonSyntaxToken | PythonSyntaxToken[];
};

function renderPythonSyntaxToken(token: PythonSyntaxToken, key: string): ReactNode {
    if (typeof token === 'string') {
        return <Fragment key={key}>{token}</Fragment>;
    }
    const aliases = Array.isArray(token.alias)
        ? token.alias
        : token.alias
            ? [token.alias]
            : [];
    const children = Array.isArray(token.content) ? token.content : [token.content];
    return (
        <span className={cn('token', token.type, ...aliases)} key={key}>
            {children.map((child, index) => renderPythonSyntaxToken(child, `${key}-${index}`))}
        </span>
    );
}

function PythonExecutionStep({ activity }: { activity: PythonActivity }) {
    const [isCodeExpanded, setIsCodeExpanded] = useState(false);
    const [isOutputExpanded, setIsOutputExpanded] = useState(false);
    const codeId = useId();
    const outputId = useId();
    const { t } = useTranslation();
    const highlightedCode = useMemo(() => {
        try {
            return Prism.tokenize(activity.code, Prism.languages.python) as PythonSyntaxToken[];
        } catch {
            return [activity.code];
        }
    }, [activity.code]);
    const statusLabel = t(`think.python.${activity.status === 'python_running'
        ? 'running'
        : activity.status === 'python_completed'
            ? 'completed'
            : 'failed'}`);

    if (!activity.code) {
        return <div className="think-block-step-title">{statusLabel}</div>;
    }

    return (
        <div className={cn('think-block-python', isCodeExpanded && 'is-code-expanded')}>
            {activity.purpose && (
                <div className="think-block-step-body think-block-python-purpose">
                    {activity.purpose}
                </div>
            )}
            <button
                type="button"
                className="think-block-python-toggle"
                onClick={() => setIsCodeExpanded((expanded) => !expanded)}
                aria-expanded={isCodeExpanded}
                aria-controls={codeId}
            >
                <span className="think-block-step-title">{statusLabel}</span>
                <span className="think-block-python-toggle-label">
                    {t(`think.python.${isCodeExpanded ? 'hideCode' : 'showCode'}`)}
                </span>
                <svg
                    className="think-block-python-chevron"
                    viewBox="0 0 20 20"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    aria-hidden="true"
                >
                    <path d="m7 5 5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
            </button>
            <div
                id={codeId}
                className="think-block-python-disclosure"
                aria-hidden={!isCodeExpanded}
                inert={!isCodeExpanded}
            >
                <div className="think-block-python-disclosure-inner">
                    <pre className="think-block-python-code" tabIndex={0}>
                        <code className="language-python">
                            {highlightedCode.map((token, index) => (
                                renderPythonSyntaxToken(token, `python-token-${index}`)
                            ))}
                        </code>
                    </pre>
                </div>
            </div>
            {activity.output && (
                <div className="think-block-python-output">
                    <button
                        type="button"
                        className="think-block-python-output-toggle"
                        onClick={() => setIsOutputExpanded((expanded) => !expanded)}
                        aria-expanded={isOutputExpanded}
                        aria-controls={outputId}
                    >
                        <span className="think-block-python-output-label">
                            {t('think.python.output')}
                        </span>
                        <span className="think-block-python-toggle-label">
                            {t(`think.python.${isOutputExpanded ? 'hideOutput' : 'showOutput'}`)}
                        </span>
                        <svg
                            className={cn('think-block-python-chevron', isOutputExpanded && 'is-expanded')}
                            viewBox="0 0 20 20"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.8"
                            aria-hidden="true"
                        >
                            <path d="m7 5 5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                    </button>
                    <div
                        id={outputId}
                        className="think-block-python-output-disclosure"
                        aria-hidden={!isOutputExpanded}
                        inert={!isOutputExpanded}
                    >
                        <div className="think-block-python-output-disclosure-inner">
                            <pre className="think-block-python-output-content">{activity.output}</pre>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

function ImageAnalysisStep({ activity }: { activity: ImageActivity }) {
    const { t } = useTranslation();
    const statusKey = activity.status === 'image_running'
        ? 'running'
        : activity.status === 'image_completed'
            ? 'completed'
            : 'failed';
    return (
        <div className="think-block-image-analysis">
            <div className="think-block-step-title">{t(`think.image.${activity.operation}.${statusKey}`)}</div>
            {activity.purpose && (
                <div className="think-block-step-body">{activity.purpose}</div>
            )}
            {activity.filename && (
                <div className="think-block-step-meta">
                    {t('think.image.source', { filename: activity.filename })}
                    {activity.imageCount > 0
                        ? ` · ${t('think.image.fragments', { count: activity.imageCount })}`
                        : ''}
                </div>
            )}
        </div>
    );
}

function ModelResponseStep({ activity }: { activity: ModelActivity }) {
    const { t } = useTranslation();
    const statusKey = activity.status === 'model_waiting'
        ? 'waiting'
        : activity.status === 'model_responded'
            ? 'responded'
            : 'failed';
    return <div className="think-block-step-title">{t(`think.model.${statusKey}`)}</div>;
}

function parseThoughtTimeline(value: string): ThoughtTimelineItem[] {
    const text = decodeThoughtEntities(String(value || '')).trim();
    if (!text) {
        return [];
    }
    const markerRegex = /<search_activity\s+data-b64="([A-Za-z0-9_+/=-]+)"\s*><\/search_activity>|<python_activity\s+data-b64="([A-Za-z0-9_+/=-]+)"\s*><\/python_activity>|<image_activity\s+data-b64="([A-Za-z0-9_+/=-]+)"\s*><\/image_activity>|<model_activity\s+data-b64="([A-Za-z0-9_+/=-]+)"\s*><\/model_activity>|\*\*([^*\n]+?)\*\*/g;
    const items: ThoughtTimelineItem[] = [];
    let cursor = 0;
    let pendingHeading: string | undefined;
    let match: RegExpExecArray | null;

    const flushThought = (body: string) => {
        const normalizedBody = body.trim();
        if (pendingHeading || normalizedBody) {
            items.push({ kind: 'thought', heading: pendingHeading, body: normalizedBody });
        }
        pendingHeading = undefined;
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
            pendingHeading = match[5].trim();
        }
        cursor = match.index + match[0].length;
    }
    flushThought(text.slice(cursor));
    const mergedItems: ThoughtTimelineItem[] = [];
    const pythonIndexes = new Map<string, number>();
    const imageIndexes = new Map<string, number>();
    const modelIndexes = new Map<string, number>();
    items.forEach((item) => {
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

export default function ThinkBlock({
    content = '',
    openTime,
    closeTime,
    isStreaming = false,
}: ThinkBlockProps) {
    const [isExpanded, setIsExpanded] = useState(false);
    const [liveNow, setLiveNow] = useState<number | null>(null);
    const contentId = useId();
    const { t } = useTranslation();
    const items = useMemo(() => parseThoughtTimeline(content), [content]);
    const headlineIndex = items.findIndex((item) => item.kind === 'thought' && item.heading);
    const headline = headlineIndex >= 0 && items[headlineIndex].kind === 'thought'
        ? items[headlineIndex].heading
        : undefined;
    const timelineItems = useMemo(() => items
        .map((item, index) => (
            index === headlineIndex && item.kind === 'thought' ? { ...item, heading: undefined } : item
        ))
        .filter((item) => (
            item.kind === 'search'
            || item.kind === 'python'
            || item.kind === 'image'
            || item.kind === 'model'
            || item.heading
            || item.body
        )), [headlineIndex, items]);
    const canExpand = timelineItems.length > 0;
    const currentSearchQuery = items
        .findLast((item) => item.kind === 'search')
        ?.query.trim();
    const runningPython = items.findLast((item) => (
        item.kind === 'python' && item.status === 'python_running'
    ));
    const runningImage = items.findLast((item): item is ImageActivity => (
        item.kind === 'image' && item.status === 'image_running'
    ));
    const waitingModel = items.findLast((item): item is ModelActivity => (
        item.kind === 'model' && item.status === 'model_waiting'
    ));

    useEffect(() => {
        if (!isStreaming || !openTime) {
            return undefined;
        }
        const initialUpdate = window.setTimeout(() => setLiveNow(Date.now()), 0);
        const interval = window.setInterval(() => setLiveNow(Date.now()), 100);
        return () => {
            window.clearTimeout(initialUpdate);
            window.clearInterval(interval);
        };
    }, [isStreaming, openTime]);

    const thinkingTime = useMemo(() => {
        if (!openTime) {
            return 0;
        }
        const endTime = closeTime || liveNow || openTime;
        return Math.max(0, endTime - openTime);
    }, [closeTime, liveNow, openTime]);

    const formattedTime = thinkingTime < 1000
        ? t('think.timeMilliseconds', { value: Math.round(thinkingTime) })
        : t('think.timeSeconds', { value: (thinkingTime / 1000).toFixed(1) });
    const label = isStreaming
        ? (runningPython
            ? t('think.python.running')
            : runningImage
                ? t(`think.image.${runningImage.operation}.running`)
                : waitingModel
                    ? t('think.model.waiting')
                    : currentSearchQuery || headline || t('think.loading'))
        : openTime
            ? t('think.completedLabel', { time: formattedTime })
            : (headline || t('think.label'));

    if (!content && !isStreaming) {
        return null;
    }

    return (
        <div className={cn('think-block-wrapper', isExpanded && 'is-expanded', isStreaming && 'is-streaming')}>
            <button
                type="button"
                className="think-block-header"
                onClick={() => {
                    if (canExpand) {
                        setIsExpanded((expanded) => !expanded);
                    }
                }}
                aria-disabled={!canExpand}
                aria-expanded={canExpand && isExpanded}
                aria-controls={contentId}
                aria-label={isExpanded ? t('think.collapse') : t('think.expand')}
            >
                <svg
                    className="think-block-icon"
                    viewBox="0 0 20 20"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    aria-hidden="true"
                >
                    <path d="m7 5 5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span className="think-block-label">{label}</span>
                {!!openTime && isStreaming && (
                    <span className="think-block-timer" aria-hidden="true">{formattedTime}</span>
                )}
            </button>

            <div
                id={contentId}
                className="think-block-disclosure"
                aria-hidden={!isExpanded}
                inert={!isExpanded}
            >
                <div className="think-block-disclosure-inner">
                    <div className="think-block-content">
                        {timelineItems.map((item, index) => (
                            <div
                                className={cn(
                                    'think-block-step',
                                    item.kind === 'search' && 'is-search',
                                    item.kind === 'python' && 'is-python',
                                    item.kind === 'image' && 'is-image',
                                    item.kind === 'model' && 'is-model',
                                )}
                                key={`${item.kind === 'thought' ? item.heading || 'step' : item.kind === 'python' || item.kind === 'image' || item.kind === 'model' ? item.id : item.status}-${index}`}
                            >
                                <span className="think-block-step-marker" aria-hidden="true">
                                    {item.kind === 'search' && (
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                                            <circle cx="12" cy="12" r="8.5" />
                                            <path d="M3.5 12h17M12 3.5c2.25 2.35 3.25 5.2 3.25 8.5s-1 6.15-3.25 8.5M12 3.5C9.75 5.85 8.75 8.7 8.75 12s1 6.15 3.25 8.5" />
                                        </svg>
                                    )}
                                    {item.kind === 'python' && (
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                                            <path d="m8 8-4 4 4 4M16 8l4 4-4 4M14 5l-4 14" strokeLinecap="round" strokeLinejoin="round" />
                                        </svg>
                                    )}
                                    {item.kind === 'image' && (
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                                            <rect x="4" y="4" width="16" height="16" rx="2" />
                                            <path d="m7 16 3.5-4 2.5 3 2-2.5L18 16M15.5 8.5h.01" strokeLinecap="round" strokeLinejoin="round" />
                                        </svg>
                                    )}
                                    {item.kind === 'model' && (
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                                            <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" strokeLinecap="round" />
                                            <circle cx="12" cy="12" r="3.5" />
                                        </svg>
                                    )}
                                </span>
                                <div className="think-block-step-copy">
                                    {item.kind === 'thought' ? (
                                        <>
                                            {item.heading && (
                                                <div className="think-block-step-title">{item.heading}</div>
                                            )}
                                            {item.body && (
                                                <div className="think-block-step-body">{item.body}</div>
                                            )}
                                        </>
                                    ) : item.kind === 'search' ? (
                                        <>
                                            <div className="think-block-step-title">
                                                {item.query || t(`webSearch.status.${item.status === 'web_search_started'
                                                        ? 'started'
                                                        : item.status === 'web_search_fetching'
                                                            ? 'fetching'
                                                            : item.status === 'web_search_done'
                                                                ? 'done'
                                                                : item.status === 'web_search_no_results'
                                                                    ? 'noResults'
                                                                    : 'failed'}`)}
                                            </div>
                                            {item.sources.length > 0 && (
                                                <WebSourcesPanel
                                                    className="think-block-sources-panel"
                                                    mode="inline"
                                                    sources={item.sources}
                                                />
                                            )}
                                        </>
                                    ) : item.kind === 'python' ? (
                                        <PythonExecutionStep activity={item} />
                                    ) : item.kind === 'image' ? (
                                        <ImageAnalysisStep activity={item} />
                                    ) : (
                                        <ModelResponseStep activity={item} />
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}
