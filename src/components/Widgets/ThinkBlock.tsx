import { useEffect, useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../utils/cn';
import WebSourcesPanel from './WebSourcesPanel';
import {
    decodeSearchActivity,
    decodeThoughtEntities,
    type DecodedSearchActivity,
} from './searchActivityUtils';

type ThoughtSection = {
    kind: 'thought';
    heading?: string;
    body: string;
};

type SearchActivity = DecodedSearchActivity & {
    kind: 'search';
};

type ThoughtTimelineItem = ThoughtSection | SearchActivity;

type ThinkBlockProps = {
    content?: string;
    openTime?: number;
    closeTime?: number;
    isStreaming?: boolean;
};

function parseThoughtTimeline(value: string): ThoughtTimelineItem[] {
    const text = decodeThoughtEntities(String(value || '')).trim();
    if (!text) {
        return [];
    }
    const markerRegex = /<search_activity\s+data-b64="([A-Za-z0-9_+/=-]+)"\s*><\/search_activity>|\*\*([^*\n]+?)\*\*/g;
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
            pendingHeading = match[2].trim();
        }
        cursor = match.index + match[0].length;
    }
    flushThought(text.slice(cursor));
    const terminalSearchQueries = new Set(items
        .filter((item): item is SearchActivity => (
            item.kind === 'search'
            && ['web_search_done', 'web_search_no_results', 'web_search_failed'].includes(item.status)
        ))
        .map((item) => item.query.trim()));
    const latestPendingSearchIndex = new Map<string, number>();
    items.forEach((item, index) => {
        if (
            item.kind === 'search'
            && ['web_search_started', 'web_search_fetching'].includes(item.status)
            && !terminalSearchQueries.has(item.query.trim())
        ) {
            latestPendingSearchIndex.set(item.query.trim(), index);
        }
    });
    return items.filter((item, index) => {
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
        .filter((item) => item.kind === 'search' || item.heading || item.body), [headlineIndex, items]);
    const canExpand = timelineItems.length > 0;
    const currentSearchQuery = items
        .findLast((item) => item.kind === 'search')
        ?.query.trim();

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
        ? (currentSearchQuery || headline || t('think.loading'))
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
                                className={cn('think-block-step', item.kind === 'search' && 'is-search')}
                                key={`${item.kind === 'thought' ? item.heading || 'step' : item.status}-${index}`}
                            >
                                <span className="think-block-step-marker" aria-hidden="true">
                                    {item.kind === 'search' && (
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                                            <circle cx="12" cy="12" r="8.5" />
                                            <path d="M3.5 12h17M12 3.5c2.25 2.35 3.25 5.2 3.25 8.5s-1 6.15-3.25 8.5M12 3.5C9.75 5.85 8.75 8.7 8.75 12s1 6.15 3.25 8.5" />
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
                                    ) : (
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
