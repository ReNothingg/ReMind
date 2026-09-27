import { Fragment, type ReactNode, useEffect, useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Brain, ChevronRight, Code2, FileText, Github, Globe, Image, ListChecks, MessageCircle, Search, Wrench } from 'lucide-react';
import Prism from 'prismjs';
import 'prismjs/components/prism-python';
import { cn } from '../../utils/cn';
import WebSourcesPanel from './WebSourcesPanel';
import { parseThoughtTimeline, type ThoughtTimelineItem, type PythonActivity } from './thoughtTimeline';

type ThinkBlockProps = {
    content?: string;
    openTime?: number;
    closeTime?: number;
    isStreaming?: boolean;
};

type RowState = 'running' | 'complete' | 'failed' | 'interrupted';

type SyntaxToken = string | { type: string; alias?: string | string[]; content: SyntaxToken | SyntaxToken[] };

function syntaxNode(token: SyntaxToken, key: string): ReactNode {
    if (typeof token === 'string') return <Fragment key={key}>{token}</Fragment>;
    const aliases = Array.isArray(token.alias) ? token.alias : token.alias ? [token.alias] : [];
    const children = Array.isArray(token.content) ? token.content : [token.content];
    return <span key={key} className={cn('token', token.type, ...aliases)}>{children.map((child, index) => syntaxNode(child, `${key}-${index}`))}</span>;
}

function CodePreview({ activity }: { activity: PythonActivity }) {
    const { t } = useTranslation();
    const tokens = useMemo(() => {
        try { return Prism.tokenize(activity.code, Prism.languages.python) as SyntaxToken[]; }
        catch { return [activity.code]; }
    }, [activity.code]);
    return <div className="think-io-card">
        {activity.code && <div className="think-io-section">
            <span className="think-io-label">{t('think.presentation.input')}</span>
            <div className="think-io-value">
                {activity.codeTruncated && <p className="think-row-note">{t('think.tools.previewTruncated')}</p>}
                <pre tabIndex={0} aria-label={t('think.presentation.input')}><code>{tokens.map((token, index) => syntaxNode(token, `code-${index}`))}</code></pre>
            </div>
        </div>}
        {activity.output && <div className="think-io-section">
            <span className="think-io-label">{t('think.presentation.output')}</span>
            <div className="think-io-value">
                {activity.outputTruncated && <p className="think-row-note">{t('think.tools.previewTruncated')}</p>}
                <pre tabIndex={0} aria-label={t('think.presentation.output')}>{activity.output}</pre>
            </div>
        </div>}
    </div>;
}

function DisclosureRow({ title, summary = '', icon, state, duration, reasoning = false, children }: {
    title: string;
    summary?: string;
    icon: ReactNode;
    state: RowState;
    duration?: string;
    reasoning?: boolean;
    children?: ReactNode;
}) {
    const [expanded, setExpanded] = useState(false);
    const bodyId = useId();
    const { t } = useTranslation();
    const expandable = Boolean(children);
    const statusLabel = state === 'complete' ? '' : t(`think.presentation.states.${state}`);
    return <div className={cn('think-row', reasoning && 'is-reasoning')} data-state={state} data-expanded={expanded || undefined}>
        <button type="button" className="think-row-trigger" aria-expanded={expandable ? expanded : undefined}
            aria-controls={expandable ? bodyId : undefined} aria-disabled={!expandable || undefined}
            onClick={() => { if (expandable) setExpanded(value => !value); }}>
            <span className="think-row-icon" aria-hidden="true">{state === 'failed' || state === 'interrupted' ? <span className="think-state-dot" /> : icon}</span>
            <span className="think-row-title">{title}</span>
            {(!expanded || !reasoning) && summary && <>
                <span className="think-row-separator" aria-hidden="true" />
                <span className="think-row-summary" data-follow-end={reasoning && state === 'running' || undefined}>
                    <span>{summary}</span>
                </span>
            </>}
            {duration && <span className="think-row-duration">{duration}</span>}
            {expandable && <ChevronRight className="think-row-chevron" aria-hidden="true" />}
            {statusLabel && statusLabel !== summary && <span className="think-sr-only">{statusLabel}</span>}
        </button>
        {expandable && <div id={bodyId} className="think-row-body" hidden={!expanded}>
            {expanded && children}
        </div>}
    </div>;
}

function stateFor(status: string, active: boolean): RowState {
    if (status.endsWith('failed') || status === 'failed') return 'failed';
    if (['running', 'python_running', 'image_running', 'model_waiting', 'web_search_started', 'web_search_fetching'].includes(status)) return active ? 'running' : 'interrupted';
    return 'complete';
}

function iconFor(name: string) {
    if (name.startsWith('web_')) return <Globe />;
    if (name.startsWith('github_')) return <Github />;
    if (name.startsWith('file_') || name.startsWith('canvas_')) return <FileText />;
    if (name === 'plan_update') return <ListChecks />;
    if (name === 'ask_user') return <MessageCircle />;
    return <Wrench />;
}

function TimelineRow({ item, active }: { item: ThoughtTimelineItem; active: boolean }) {
    const { t } = useTranslation();
    const timeLabel = (milliseconds: number) => milliseconds < 1000 ? t('think.timeMilliseconds', { value: Math.round(milliseconds) }) : t('think.timeSeconds', { value: (milliseconds / 1000).toFixed(1) });
    if (item.kind === 'thought') {
        const text = item.body.trim();
        const lines = text.split('\n').map(line => line.trim()).filter(Boolean);
        const summary = (active ? lines.at(-1) : lines[0])?.replaceAll('**', '') || '';
        return <DisclosureRow title={t('think.presentation.think')} summary={summary} icon={<Brain />} state={active ? 'running' : 'complete'} reasoning>
            <div className="think-reasoning-body">{text}</div>
        </DisclosureRow>;
    }
    if (item.kind === 'tool' && item.name === 'model_progress') {
        return <p className="think-commentary">{item.detail}</p>;
    }
    const state = stateFor(item.status, active);
    if (item.kind === 'python') {
        return <DisclosureRow title={t('composer.tools.python')} summary={item.purpose || t(`think.presentation.states.${state}`)} icon={<Code2 />} state={state}
            duration={item.durationMs > 0 ? timeLabel(item.durationMs) : undefined}>
            {(item.code || item.output) && <CodePreview activity={item} />}
        </DisclosureRow>;
    }
    if (item.kind === 'search') {
        return <div className="think-search-step" data-state={state}>
            <Search className="think-search-icon" aria-hidden="true" />
            <div className="think-search-copy">
                <div className="think-search-query">{item.query || t('think.presentation.search')}</div>
                {item.sources.length > 0 ? <WebSourcesPanel mode="inline" className="think-search-sources" sources={item.sources} /> : <div className="think-row-note">{t(state === 'failed' ? 'webSearch.status.failed' : state === 'running' ? 'webSearch.status.fetching' : state === 'interrupted' ? 'think.presentation.states.interrupted' : 'webSearch.status.noResults')}</div>}
            </div>
        </div>;
    }
    if (item.kind === 'image') {
        return <DisclosureRow title={t('composer.tools.image_analysis')} summary={item.filename || item.purpose} icon={<Image />} state={state}>
            <div className="think-detail-card">
                {item.purpose && <p>{item.purpose}</p>}
                {item.filename && <p className="think-row-note">{t('think.image.source', { filename: item.filename })}</p>}
                {item.imageCount > 0 && <p className="think-row-note">{t('think.image.fragments', { count: item.imageCount })}</p>}
            </div>
        </DisclosureRow>;
    }
    if (item.kind === 'model') {
        return <DisclosureRow title={t('think.presentation.model')} summary={state === 'interrupted' ? t('think.presentation.states.interrupted') : t(`think.model.${state === 'running' ? 'waiting' : state === 'failed' ? 'failed' : 'responded'}`)} icon={<Brain />} state={state} />;
    }
    const name = t(`think.tools.names.${item.name}`, { defaultValue: t('think.tools.generic') });
    const error = item.error ? t(`think.tools.errors.${item.error}`, { defaultValue: t('think.tools.error') }) : '';
    return <DisclosureRow title={name} summary={error || item.detail} icon={iconFor(item.name)} state={state}
        duration={item.durationMs > 0 ? timeLabel(item.durationMs) : undefined}>
        <div className="think-io-card">
            {item.detail && <div className="think-io-section"><span className="think-io-label">{t('think.presentation.details')}</span><div className="think-io-value">{item.detail}</div></div>}
            <div className="think-io-section"><span className="think-io-label">{t('think.presentation.status')}</span><div className="think-io-value" data-error={state === 'failed' || undefined}>{error || t(`think.presentation.states.${state}`)}</div></div>
        </div>
    </DisclosureRow>;
}

export default function ThinkBlock({ content = '', openTime, closeTime, isStreaming = false }: ThinkBlockProps) {
    const { t } = useTranslation();
    const [expanded, setExpanded] = useState<boolean | null>(null);
    const [now, setNow] = useState<number | null>(null);
    const contentId = useId();
    const parsed = useMemo(() => parseThoughtTimeline(content), [content]);
    const items = useMemo(() => parsed.filter(item => item.kind !== 'model' || item.status === 'model_failed' || (!isStreaming && item.status === 'model_waiting')), [parsed, isStreaming]);
    const open = isStreaming || (expanded ?? false);
    const toolCount = items.filter(item => item.kind !== 'thought' && item.kind !== 'model' && !(item.kind === 'tool' && item.name === 'model_progress')).length;
    const messageCount = items.filter(item => item.kind === 'tool' && item.name === 'model_progress').length;
    const labels = [toolCount > 0 ? t('think.presentation.toolCount', { count: toolCount }) : '', messageCount > 0 ? t('think.presentation.messageCount', { count: messageCount }) : ''].filter(Boolean);
    const title = labels.join(' · ') || t('think.label');
    const elapsed = openTime ? Math.max(0, (closeTime || now || openTime) - openTime) : 0;
    const duration = t('think.timeSeconds', { value: (elapsed / 1000).toFixed(1) });
    const lastThought = parsed.findLastIndex(item => item.kind === 'thought');
    const thoughtIsActive = isStreaming && lastThought === parsed.length - 1;
    useEffect(() => {
        if (!isStreaming || !openTime) return;
        const timer = window.setInterval(() => setNow(Date.now()), 250);
        return () => window.clearInterval(timer);
    }, [isStreaming, openTime]);
    if (!content && !isStreaming) return null;
    return <section className={cn('think-block-wrapper', open && 'is-expanded', isStreaming && 'is-streaming')}>
        {!isStreaming && items.length > 0 && <button className="think-block-header" type="button" aria-expanded={open} aria-controls={contentId} onClick={() => setExpanded(!open)}>
            <span className="think-block-label">{title}</span>
            <ChevronRight className="think-block-icon" aria-hidden="true" />
            {openTime ? <span className="think-block-timer">{duration}</span> : null}
        </button>}
        <div id={contentId} className="think-block-content" hidden={!open}>
            {items.map((item, index) => <TimelineRow key={item.kind === 'thought' ? `thought-${index}` : item.kind === 'search' ? `search-${index}` : `${item.kind}-${item.id}`}
                item={item} active={item.kind === 'thought' ? thoughtIsActive && item === parsed[lastThought] : isStreaming} />)}
        </div>
        {isStreaming && <div className="think-block-pending"><span role="status">{t('think.presentation.working')}</span>{openTime ? <span className="think-block-timer">{duration}</span> : null}</div>}
    </section>;
}
