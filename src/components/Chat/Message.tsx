import { useEffect, useLayoutEffect, useRef, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { formatText, formatPlainText, formatUserText, highlightCode } from '../../utils/formatting';
import { apiService } from '../../services/api';
import { fileService } from '../../services/fileService';
import Quiz from '../Widgets/Quiz';
import Spinwheel from '../Widgets/Spinwheel';
import Beatbox from '../Widgets/Beatbox';
import ThinkBlock from '../Widgets/ThinkBlock';
import { useAudio } from '../../hooks/useAudio';
import { Utils } from '../../utils/utils';
import TranslationPanel from './TranslationPanel';
import { useSettings } from '../../context/SettingsContext';
import { cn } from '../../utils/cn';

const MessageActionButton = ({ className, title, onClick, children, disabled = false }) => (
    <button
        type="button"
        className={cn('action-btn ui-action-button', className)}
        title={title}
        onClick={onClick}
        disabled={disabled}
    >
        {children}
    </button>
);

const MessageImageAttachment = ({ src, alt, messageId, isInteractive }) => {
    const [isLoaded, setIsLoaded] = useState(false);
    const [hasError, setHasError] = useState(false);
    const { t } = useTranslation();

    useEffect(() => {
        const frame = window.requestAnimationFrame(() => {
            setIsLoaded(false);
            setHasError(false);
        });

        return () => window.cancelAnimationFrame(frame);
    }, [src]);

    const imageContent = (
        <>
            {!hasError && (
                <>
                    {!isLoaded && (
                        <span className="message-image-loader" aria-hidden="true">
                            <span className="message-image-loader-shimmer" />
                        </span>
                    )}
                    <img
                        className="attached-img message-image-element"
                        src={src}
                        alt={alt}
                        loading="lazy"
                        decoding="async"
                        onLoad={() => setIsLoaded(true)}
                        onError={() => {
                            setHasError(true);
                            setIsLoaded(false);
                        }}
                    />
                </>
            )}
            {hasError && (
                <span className="message-image-fallback">
                    <span className="message-image-fallback-title">
                        {t('chatImage.unavailableTitle', { defaultValue: 'Превью недоступно' })}
                    </span>
                    <span className="message-image-fallback-subtitle">
                        {t('chatImage.unavailableDescription', {
                            defaultValue: 'Изображение не удалось загрузить.',
                        })}
                    </span>
                </span>
            )}
            {isInteractive && !hasError && (
                <span className="message-image-overlay" aria-hidden="true">
                    <span className="message-image-overlay-chip">
                        {t('chatImage.open', { defaultValue: 'Открыть' })}
                    </span>
                </span>
            )}
        </>
    );

    return (
        <div className={cn('message-image-card', isLoaded && 'is-loaded', hasError && 'is-error')}>
            {isInteractive ? (
                <button
                    type="button"
                    className="message-image-button is-interactive"
                    onClick={() => {
                        if (window.openImageLightbox) {
                            window.openImageLightbox(src, messageId);
                        }
                    }}
                    aria-label="Open image preview"
                >
                    {imageContent}
                </button>
            ) : (
                <div className="message-image-button is-static" role="img" aria-label={alt}>
                    {imageContent}
                </div>
            )}
        </div>
    );
};

const sourceFallbackIcon = '/icons/ui/web.svg';

const normalizeWebSource = (source, index, sourceFallbackLabel = 'Source') => {
    const fallbackTitle = `${sourceFallbackLabel} ${index + 1}`;
    if (typeof source === 'string') {
        const isUrl = /^https?:\/\//i.test(source);
        let siteName = fallbackTitle;
        if (isUrl) {
            try {
                siteName = new URL(source).hostname.replace(/^www\./, '');
            } catch {
                siteName = fallbackTitle;
            }
        }
        return {
            rank: index + 1,
            title: siteName,
            url: isUrl ? source : '',
            displayUrl: isUrl ? siteName : source,
            siteName,
            snippet: '',
            faviconUrl: sourceFallbackIcon
        };
    }

    if (!source || typeof source !== 'object') {
        return null;
    }

    const url = String(source.url || source.final_url || source.finalUrl || '').trim();
    let siteName = String(source.site_name || source.siteName || '').trim();
    if (!siteName && url) {
        try {
            siteName = new URL(url).hostname.replace(/^www\./, '');
        } catch {
            siteName = '';
        }
    }

    const title = String(source.title || siteName || fallbackTitle).trim();
    return {
        rank: source.rank || index + 1,
        title,
        url,
        displayUrl: String(source.display_url || source.displayUrl || siteName || url).trim(),
        siteName: siteName || title,
        snippet: String(source.snippet || '').trim(),
        faviconUrl: String(source.favicon_url || source.faviconUrl || '').trim() || sourceFallbackIcon
    };
};

const normalizeWebSources = (sources, sourceFallbackLabel = 'Source') => (Array.isArray(sources) ? sources : [])
    .map((source, index) => normalizeWebSource(source, index, sourceFallbackLabel))
    .filter(Boolean)
    .filter((source) => source.url || source.title);

const linkifySourceCitations = (text, sources) => {
    if (!text || !Array.isArray(sources) || sources.length === 0) {
        return text || '';
    }

    const sourceByRank = new Map();
    sources.forEach((source, index) => {
        sourceByRank.set(Number(source.rank || index + 1), source);
    });

    const replaceCitation = (segment) => segment.replace(/(^|[\n.!?])([^.!?\n]*?\S)\s*\[(\d+(?:\s*,\s*\d+)*)\](?!\s*[:(])/g, (match, prefix, claimText, ranksText) => {
        const ranks = ranksText
            .split(',')
            .map((rank) => Number(rank.trim()))
            .filter((rank) => Number.isFinite(rank) && sourceByRank.has(rank));

        if (ranks.length === 0) {
            return match;
        }

        return `${prefix}<c s="${ranks.join(',')}">${claimText}</c>`;
    });

    return String(text)
        .split(/(```[\s\S]*?```|`[^`\n]+`)/g)
        .map((segment, index) => (index % 2 === 0 ? replaceCitation(segment) : segment))
        .join('');
};

const normalizeComparableSourceUrl = (url) => {
    const rawUrl = String(url || '').trim();
    if (!rawUrl) {
        return '';
    }

    try {
        const parsed = new URL(rawUrl, window.location.origin);
        parsed.hash = '';
        return parsed.toString().replace(/\/$/, '');
    } catch {
        return rawUrl.replace(/#.*$/, '').replace(/\/$/, '');
    }
};

const appendTextNode = (documentRef, parent, tagName, className, text) => {
    const value = String(text || '').trim();
    if (!value) {
        return null;
    }

    const element = documentRef.createElement(tagName);
    if (className) {
        element.className = className;
    }
    element.textContent = value;
    parent.appendChild(element);
    return element;
};

const parseSourceIds = (value) => String(value || '')
    .split(',')
    .map((rank) => Number(rank.trim()))
    .filter(Number.isFinite);

const buildSourceCitationPopover = (documentRef, sources, fragmentSourcesLabel = 'Fragment sources') => {
    const popover = documentRef.createElement('span');
    popover.className = 'source-citation-popover';
    popover.setAttribute('aria-hidden', 'true');

    const sourceList = Array.isArray(sources) ? sources.filter(Boolean) : [];
    if (sourceList.length === 0) {
        return popover;
    }

    if (sourceList.length === 1) {
        const [source] = sourceList;
        const header = documentRef.createElement('span');
        header.className = 'source-citation-popover-header';
        const icon = documentRef.createElement('img');
        icon.className = 'source-citation-popover-icon';
        icon.src = source.faviconUrl || sourceFallbackIcon;
        icon.alt = '';
        icon.loading = 'lazy';
        header.appendChild(icon);
        appendTextNode(documentRef, header, 'strong', '', source.title || source.siteName);
        popover.appendChild(header);
        appendTextNode(documentRef, popover, 'span', 'source-citation-popover-snippet', source.snippet);
        appendTextNode(documentRef, popover, 'small', '', source.displayUrl || source.url);
        return popover;
    }

    appendTextNode(documentRef, popover, 'strong', 'source-citation-popover-title', fragmentSourcesLabel);
    sourceList.forEach((source) => {
        const row = documentRef.createElement('span');
        row.className = 'source-citation-popover-row';
        const icon = documentRef.createElement('img');
        icon.className = 'source-citation-popover-icon';
        icon.src = source.faviconUrl || sourceFallbackIcon;
        icon.alt = '';
        icon.loading = 'lazy';
        row.appendChild(icon);
        appendTextNode(documentRef, row, 'span', '', source.siteName || source.title || source.displayUrl);
        popover.appendChild(row);
    });
    return popover;
};

const decorateSourceCitations = (html, sources, labels: { fragmentSources?: string } = {}) => {
    if (!html || typeof document === 'undefined' || !Array.isArray(sources) || sources.length === 0) {
        return html || '';
    }

    const sourcesByUrl = new Map();
    const sourcesByRank = new Map();
    sources.forEach((source) => {
        const normalizedUrl = normalizeComparableSourceUrl(source.url);
        if (normalizedUrl) {
            sourcesByUrl.set(normalizedUrl, source);
        }
        sourcesByRank.set(Number(source.rank), source);
    });

    if (sourcesByUrl.size === 0 && sourcesByRank.size === 0) {
        return html;
    }

    const template = document.createElement('template');
    template.innerHTML = html;

    template.content.querySelectorAll('c[s], mark[data-source-ids]').forEach((mark) => {
        const markSources = parseSourceIds(mark.getAttribute('s') || mark.getAttribute('data-source-ids'))
            .map((rank) => sourcesByRank.get(rank))
            .filter(Boolean);
        if (markSources.length === 0) {
            return;
        }

        mark.classList.add('source-citation-mark');
        mark.setAttribute('tabindex', '0');
        mark.appendChild(buildSourceCitationPopover(
            document,
            markSources,
            labels.fragmentSources || 'Fragment sources'
        ));
    });

    template.content.querySelectorAll('a[href]').forEach((link) => {
        if (link.closest('.source-citation-mark')) {
            return;
        }

        const source = sourcesByUrl.get(normalizeComparableSourceUrl(link.getAttribute('href')));
        if (!source) {
            return;
        }

        link.classList.add('source-citation-link');
        link.setAttribute('target', '_blank');
        link.setAttribute('rel', 'noopener noreferrer');
        link.appendChild(buildSourceCitationPopover(
            document,
            [source],
            labels.fragmentSources || 'Fragment sources'
        ));
    });

    return template.innerHTML;
};

const WebSourcesPanel = ({ sources, t }) => {
    const normalizedSources = useMemo(
        () => normalizeWebSources(sources, t('webSearch.sourceFallback', { defaultValue: 'Source' })),
        [sources, t]
    );

    if (normalizedSources.length === 0) {
        return null;
    }

    const renderPillContent = (source) => (
        <>
            <span className="source-pill-icon-wrap" aria-hidden="true">
                <img
                    className="source-favicon"
                    src={source.faviconUrl}
                    alt=""
                    loading="lazy"
                    onError={(event) => {
                        if (event.currentTarget.dataset.fallbackApplied !== 'true') {
                            event.currentTarget.dataset.fallbackApplied = 'true';
                            event.currentTarget.src = sourceFallbackIcon;
                        }
                    }}
                />
            </span>
            <span className="source-pill-name">{source.siteName}</span>
            <span className="source-tooltip" role="tooltip">
                <strong>{source.title}</strong>
                {source.snippet && <span>{source.snippet}</span>}
                {source.displayUrl && <small>{source.displayUrl}</small>}
            </span>
        </>
    );

    return (
        <div className="web-sources-container" aria-label={t('webSearch.sourcesAria')}>
            <div className="web-sources-trigger" tabIndex={0} role="group">
                <img src="/icons/ui/web.svg" alt="" aria-hidden="true" />
                <span>{t('webSearch.sourcesLabel')}</span>
                <span className="web-sources-count">{normalizedSources.length}</span>
            </div>
            <div className="web-sources-pills">
                {normalizedSources.map((source, index) => (
                    source.url ? (
                        <a
                            key={`${source.url}-${index}`}
                            className="source-pill"
                            href={source.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            aria-label={source.title}
                        >
                            {renderPillContent(source)}
                        </a>
                    ) : (
                        <span key={`${source.title}-${index}`} className="source-pill">
                            {renderPillContent(source)}
                        </span>
                    )
                ))}
            </div>
        </div>
    );
};

const WebSearchProgress = ({ status, t }) => {
    if (!status) {
        return null;
    }

    const label = String(status.message || t('webSearch.status.started')).trim();
    const query = typeof status.query === 'string' ? status.query.trim() : '';

    return (
        <div className="web-search-progress" role="status" aria-live="polite">
            <span className="web-search-progress-icon" aria-hidden="true">
                <span />
            </span>
            <span className="web-search-progress-body">
                <span className="web-search-progress-line">
                    <span className="web-search-progress-text">{label}</span>
                    <span className="web-search-progress-dots" aria-hidden="true">
                        <span />
                        <span />
                        <span />
                    </span>
                </span>
                {query && (
                    <span className="web-search-progress-query" title={query}>
                        <span>{t('webSearch.queryLabel', { defaultValue: 'Query' })}</span>
                        <b>{query}</b>
                    </span>
                )}
            </span>
        </div>
    );
};

const Message = ({ message, onRegenerate, onEdit, onSwitchVariant }) => {
    const { role, content, images, files, sources, isLoading, isError, isGeneratingImage, imagePrompt, widgetUpdate, variants, currentVariantIndex, parts, webSearchStatus } = message;
    const isUser = role === 'user';
    const { settings } = useSettings();
    const { t } = useTranslation();
    const [isEditingUserMessage, setIsEditingUserMessage] = useState(false);
    const [editedContent, setEditedContent] = useState(content);
    const currentVariant = variants && variants.length > 0 && currentVariantIndex !== undefined
        ? variants[currentVariantIndex]
        : null;
    const filesFromParts = useMemo(() => {
        if (files && files.length > 0) return files;
        if (!parts || !Array.isArray(parts)) return [];
        return parts.filter(p => p.file).map(p => ({
            file: {
                url_path: p.file.url_path || p.file,
                original_name: p.file.original_name || p.file.name || 'file',
                mime_type: p.file.mime_type || 'application/octet-stream',
                size: p.file.size || 0
            }
        }));
    }, [files, parts]);
    const imagesFromParts = useMemo(() => {
        if (images && images.length > 0) return images;
        if (!parts || !Array.isArray(parts)) return [];
        return parts.filter(p => p.image).map(p => p.image.url_path || p.image);
    }, [images, parts]);

    let displayContent = currentVariant ? currentVariant.content : content;
    if (displayContent) {
        displayContent = displayContent.replace(/\{[^{}]*"url_path"[^{}]*\}/g, '');
        displayContent = displayContent.replace(/\{[^{}]*"original_name"[^{}]*\}/g, '');
        displayContent = displayContent.replace(/---\s*File:\s*[^-\n]+---[\s\S]*?---\s*End\s*File\s*---/gi, '');
        displayContent = displayContent.replace(/\[Binary\s+file:[^\]]+\]/gi, '');
        displayContent = displayContent.trim();
    }

    const displayImages = currentVariant ? (currentVariant.images || []) : imagesFromParts;
    const displayFiles = filesFromParts;
    const displaySources = currentVariant ? (currentVariant.sources || []) : (sources || []);
    const sourceFallbackLabel = t('webSearch.sourceFallback', { defaultValue: 'Source' });
    const displaySourceItems = useMemo(
        () => normalizeWebSources(displaySources, sourceFallbackLabel),
        [displaySources, sourceFallbackLabel]
    );
    const displayContentWithSourceLinks = useMemo(
        () => linkifySourceCitations(displayContent || '', displaySourceItems),
        [displayContent, displaySourceItems]
    );
    const hasMultipleVariants = variants && variants.length > 1;
    const contentRef = useRef(null);
    const waveformCanvasRef = useRef(null);
    const [widgets, setWidgets] = useState([]);
    const [showTranslation, setShowTranslation] = useState(false);
    const audio = useAudio(message.id);
    useEffect(() => {
        if (!isUser) {
            const newWidgets = [];
            const fromBase64 = (str) => {
                try {
                    return decodeURIComponent(escape(atob(str)));
                } catch (e) {
                    console.warn('Base64 decoding failed:', e);
                    return str;
                }
            };
            if (parts && Array.isArray(parts)) {
                parts.forEach((part, partIdx) => {
                    if (part.text && typeof part.text === 'string') {
                        const text = part.text;
                        const beatboxRegex = /<beatbox>([\s\S]*?)<\/beatbox>/gi;
                        let beatboxMatch;
                        let beatboxIdx = 0;
                        while ((beatboxMatch = beatboxRegex.exec(text)) !== null) {
                            try {
                                const state = JSON.parse(beatboxMatch[1].trim());
                                newWidgets.push({
                                    type: 'beatbox',
                                    id: `beatbox-${message.id}-${partIdx}-${beatboxIdx}`,
                                    state
                                });
                                beatboxIdx++;
                            } catch (e) {
                                console.warn('Failed to parse beatbox from parts', e, beatboxMatch[1]);
                            }
                        }
                        const quizRegex = /<quiz>([\s\S]*?)<\/quiz>/gi;
                        let quizMatch;
                        let quizIdx = 0;
                        while ((quizMatch = quizRegex.exec(text)) !== null) {
                            try {
                                const state = JSON.parse(quizMatch[1].trim());
                                newWidgets.push({
                                    type: 'quiz',
                                    id: `quiz-${message.id}-${partIdx}-${quizIdx}`,
                                    state
                                });
                                quizIdx++;
                            } catch (e) {
                                console.warn('Failed to parse quiz from parts', e, quizMatch[1]);
                            }
                        }
                        const spinwheelRegex = /<spinwheel>([\s\S]*?)<\/spinwheel>/gi;
                        let spinwheelMatch;
                        let spinwheelIdx = 0;
                        while ((spinwheelMatch = spinwheelRegex.exec(text)) !== null) {
                            try {
                                const state = JSON.parse(spinwheelMatch[1].trim());
                                newWidgets.push({
                                    type: 'spinwheel',
                                    id: `spinwheel-${message.id}-${partIdx}-${spinwheelIdx}`,
                                    state
                                });
                                spinwheelIdx++;
                            } catch (e) {
                                console.warn('Failed to parse spinwheel from parts', e, spinwheelMatch[1]);
                            }
                        }
                        const thinkRegex = /<think(?:\s+data-open="(\d+)")?(?:\s+data-close="(\d+)")?>([\s\S]*?)<\/think>/gi;
                        let thinkMatch;
                        let thinkIdx = 0;
                        while ((thinkMatch = thinkRegex.exec(text)) !== null) {
                            try {
                                const openTime = thinkMatch[1] ? parseInt(thinkMatch[1], 10) : Date.now();
                                const closeTime = thinkMatch[2] ? parseInt(thinkMatch[2], 10) : Date.now();
                                const content = thinkMatch[3].trim();
                                newWidgets.push({
                                    type: 'think',
                                    id: `think-${message.id}-${partIdx}-${thinkIdx}`,
                                    content,
                                    openTime,
                                    closeTime
                                });
                                thinkIdx++;
                            } catch (e) {
                                console.warn('Failed to parse think from parts', e, thinkMatch[0]);
                            }
                        }
                    }
                });
            }
            if (contentRef.current && displayContent) {
                const beatboxHosts = contentRef.current.querySelectorAll('.beatbox-instance-host');
                const quizHosts = contentRef.current.querySelectorAll('.quiz-instance-host');
                const spinwheelHosts = contentRef.current.querySelectorAll('.spinwheel-instance-host');
                const thinkHosts = contentRef.current.querySelectorAll('.think-instance-host');

                beatboxHosts.forEach((host, idx) => {
                    let stateJson = host.getAttribute('data-beatbox-state-b64') || host.getAttribute('data-beatbox-state');
                    if (stateJson) {
                        try {
                            if (host.getAttribute('data-beatbox-state-b64')) {
                                stateJson = fromBase64(stateJson);
                            }
                            const state = JSON.parse(stateJson);
                            const existingId = `beatbox-${message.id}-${idx}`;
                            if (!newWidgets.some(w => w.id === existingId)) {
                                newWidgets.push({
                                    type: 'beatbox',
                                    id: existingId,
                                    state
                                });
                            }
                        } catch (e) {
                            console.warn('Failed to parse beatbox state', e, stateJson);
                        }
                    }
                });

                quizHosts.forEach((host, idx) => {
                    let stateJson = host.getAttribute('data-quiz-state-b64') || host.getAttribute('data-quiz-state');
                    if (stateJson) {
                        try {
                            if (host.getAttribute('data-quiz-state-b64')) {
                                stateJson = fromBase64(stateJson);
                            }
                            const state = JSON.parse(stateJson);
                            const existingId = `quiz-${message.id}-${idx}`;
                            if (!newWidgets.some(w => w.id === existingId)) {
                                newWidgets.push({
                                    type: 'quiz',
                                    id: existingId,
                                    state
                                });
                            }
                        } catch (e) {
                            console.warn('Failed to parse quiz state', e, stateJson);
                        }
                    }
                });

                spinwheelHosts.forEach((host, idx) => {
                    let stateJson = host.getAttribute('data-spinwheel-state-b64') || host.getAttribute('data-spinwheel-state');
                    if (stateJson) {
                        try {
                            if (host.getAttribute('data-spinwheel-state-b64')) {
                                stateJson = fromBase64(stateJson);
                            }
                            const state = JSON.parse(stateJson);
                            const existingId = `spinwheel-${message.id}-${idx}`;
                            if (!newWidgets.some(w => w.id === existingId)) {
                                newWidgets.push({
                                    type: 'spinwheel',
                                    id: existingId,
                                    state
                                });
                            }
                        } catch (e) {
                            console.warn('Failed to parse spinwheel state', e, stateJson);
                        }
                    }
                });

                thinkHosts.forEach((host, idx) => {
                    const openTime = host.getAttribute('data-think-open');
                    const closeTime = host.getAttribute('data-think-close');
                    const content = host.getAttribute('data-think-content');
                    if (content && openTime && closeTime) {
                        const existingId = `think-${message.id}-${idx}`;
                        if (!newWidgets.some(w => w.id === existingId)) {
                            newWidgets.push({
                                type: 'think',
                                id: existingId,
                                content,
                                openTime: parseInt(openTime, 10),
                                closeTime: parseInt(closeTime, 10)
                            });
                        }
                    }
                });
                beatboxHosts.forEach(host => {
                    if (!host.hasAttribute('data-from-parts')) {
                        host.remove();
                    }
                });
                quizHosts.forEach(host => {
                    if (!host.hasAttribute('data-from-parts')) {
                        host.remove();
                    }
                });
                spinwheelHosts.forEach(host => {
                    if (!host.hasAttribute('data-from-parts')) {
                        host.remove();
                    }
                });
                thinkHosts.forEach(host => {
                    if (!host.hasAttribute('data-from-parts')) {
                        host.remove();
                    }
                });
            }
            setTimeout(() => {
                setWidgets(newWidgets);
            }, 0);
        }
    }, [displayContent, isUser, message.id, parts]);
    useEffect(() => {
        if (widgetUpdate && !isUser) {
            const { tag, state } = widgetUpdate;
            try {
                let widgetState = state;
                if (typeof state === 'string') {
                    try {
                        widgetState = JSON.parse(state);
                    } catch {
                        widgetState = state;
                    }
                }
                setTimeout(() => {
                    setWidgets(prev => {
                        const existingIndex = prev.findLastIndex(w => w.type === tag);
                        if (existingIndex !== -1) {
                            return prev.map((w, idx) =>
                                idx === existingIndex
                                    ? { ...w, state: widgetState }
                                    : w
                            );
                        } else {
                            return [...prev, {
                                type: tag,
                                id: `${tag}-${message.id}-${Date.now()}`,
                                state: widgetState
                            }];
                        }
                    });
                }, 0);
            } catch (error) {
                console.warn('Failed to update widget', error);
            }
        }
    }, [widgetUpdate, message.id, isUser]);

    const markdownEnabledForMessage = isUser ? !!settings.renderUserMarkdown : !!settings.renderMarkdown;
    const htmlContent = useMemo(() => {
        if (isUser) {
            return markdownEnabledForMessage ? formatUserText(content || '') : formatPlainText(content || '');
        }
        if (!markdownEnabledForMessage) {
            return formatPlainText(displayContent || '');
        }

        return decorateSourceCitations(
            formatText(displayContentWithSourceLinks),
            displaySourceItems,
            {
                fragmentSources: t('webSearch.fragmentSources')
            }
        );
    }, [displayContent, displayContentWithSourceLinks, displaySourceItems, isUser, content, markdownEnabledForMessage, t]);

    useLayoutEffect(() => {
        if (!markdownEnabledForMessage || !contentRef.current) return;

        const currentRef = contentRef.current;

        const applySyntaxHighlighting = () => {
            highlightCode(currentRef);

            const codeBlocks = currentRef.querySelectorAll('pre.line-numbers');
            codeBlocks.forEach(pre => {
                if (window.Prism?.plugins?.lineNumbers) {
                    try {
                        window.Prism.plugins.lineNumbers.resize(pre);
                    } catch (e) {
                        console.warn('Failed to initialize line numbers:', e);
                    }
                }
            });

            const codeBlockContents = currentRef.querySelectorAll('.code-block-content');
            codeBlockContents.forEach(content => {
                if (!content.dataset.initialMaxHeight) {
                    const computedStyle = window.getComputedStyle(content);
                    const maxHeight = computedStyle.maxHeight || '200px';
                    content.dataset.initialMaxHeight = maxHeight;
                    content.style.maxHeight = maxHeight;
                }

                if (!content.classList.contains('expanded')) {
                    const initialMaxHeight = parseInt(content.dataset.initialMaxHeight || '200', 10);
                    if (content.scrollHeight > initialMaxHeight) {
                        content.classList.add('has-overflow');
                    } else {
                        content.classList.remove('has-overflow');
                    }
                }
            });
        };

        applySyntaxHighlighting();
        const frame = window.requestAnimationFrame(applySyntaxHighlighting);

        return () => {
            window.cancelAnimationFrame(frame);
        };
    }, [htmlContent, isLoading, markdownEnabledForMessage, settings.theme, widgets, currentVariantIndex, variants?.length]);

    useEffect(() => {
        if (!markdownEnabledForMessage || !contentRef.current) return;

        const renderVisuals = async () => {
            if (Utils.renderSvgPreviews) {
                Utils.renderSvgPreviews();
                requestAnimationFrame(() => {
                    Utils.renderSvgPreviews();
                });
            }

            if (Utils.renderCharts) {
                await Utils.renderCharts();
            }

            if (Utils.renderD3) {
                await Utils.renderD3();
            }

            if (Utils.renderNomnoml) {
                await Utils.renderNomnoml();
            }

            if (Utils.renderMermaid) {
                await Utils.renderMermaid();
            }

            if (Utils.attachDiagramPan) {
                Utils.attachDiagramPan();
            }
        };

        renderVisuals();
    }, [htmlContent, isLoading, markdownEnabledForMessage, settings.theme, widgets, currentVariantIndex, variants?.length]);
    useEffect(() => {
        if (!audio.isVisible || !waveformCanvasRef.current || !audio.waveformPoints) return;
        const canvas = waveformCanvasRef.current;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const { width, height } = canvas;
        ctx.clearRect(0, 0, width, height);
        const barWidth = width / audio.waveformPoints.length;
        const progressRatio = audio.totalDuration > 0 ? audio.currentTime / audio.totalDuration : 0;
        const progressPx = progressRatio * width;

        audio.waveformPoints.forEach((point, index) => {
            const x = index * barWidth;
            ctx.fillStyle = x < progressPx ? 'rgba(255, 255, 255, 0.9)' : 'rgba(255, 255, 255, 0.4)';
            ctx.fillRect(x, (height - point * height) / 2, Math.max(1, barWidth * 0.8), point * height);
        });
    }, [audio.isVisible, audio.currentTime, audio.totalDuration, audio.waveformPoints]);
    useEffect(() => {
        if (!markdownEnabledForMessage || !contentRef.current) return;

        const handleClick = (e) => {
            const target = e.target.closest('button');
            if (!target) return;

            if (target.classList.contains('table-copy-btn')) {
                e.preventDefault();
                const wrapper = target.closest('.table-wrapper');
                const table = wrapper?.querySelector?.('table');
                if (!table) return;

                const tableHtml = table.outerHTML;
                const blob = new Blob([tableHtml], { type: 'text/html' });

                const originalText = target.textContent;
                const applySuccessUI = () => {
                    target.textContent = '✓ Скопировано';
                    target.style.background = 'rgba(110, 231, 183, 0.15)';
                    setTimeout(() => {
                        target.textContent = originalText;
                        target.style.background = '';
                    }, 2000);
                };

                const applyErrorUI = () => {
                    target.textContent = 'Ошибка';
                    target.style.background = 'rgba(239, 68, 68, 0.15)';
                    setTimeout(() => {
                        target.textContent = originalText;
                        target.style.background = '';
                    }, 2000);
                };
                try {
                    if (navigator.clipboard?.write && typeof ClipboardItem !== 'undefined') {
                        const data = [new ClipboardItem({ 'text/html': blob })];
                        navigator.clipboard.write(data).then(applySuccessUI).catch(() => {
                            navigator.clipboard?.writeText?.(table.innerText || table.textContent || '').then(applySuccessUI).catch(applyErrorUI);
                        });
                    } else if (navigator.clipboard?.writeText) {
                        navigator.clipboard.writeText(table.innerText || table.textContent || '').then(applySuccessUI).catch(applyErrorUI);
                    } else {
                        applyErrorUI();
                    }
                } catch {
                    applyErrorUI();
                }
                return;
            }

            const codeBlock = target.closest('.code-block');
            if (!codeBlock) return;

            const codeElement = codeBlock.querySelector('code');
            if (!codeElement) return;

            const codeText = codeElement.textContent || '';

            if (target.classList.contains('code-tab-btn')) {
                const tab = target.dataset.tab;
                if (!tab) return;

                const tabs = codeBlock.querySelectorAll('.code-tab-btn');
                tabs.forEach(btn => btn.classList.toggle('active', btn === target));

                const panes = codeBlock.querySelectorAll('.code-block-pane');
                panes.forEach(pane => pane.classList.toggle('active', pane.dataset.pane === tab));

                if (tab === 'code') {
                    const content = codeBlock.querySelector('.code-block-content');
                    if (content) {
                        if (!content.dataset.initialMaxHeight) {
                            const computedStyle = window.getComputedStyle(content);
                            const maxHeight = computedStyle.maxHeight || '200px';
                            content.dataset.initialMaxHeight = maxHeight;
                            content.style.maxHeight = maxHeight;
                        }

                        requestAnimationFrame(() => {
                            if (!content.classList.contains('expanded')) {
                                const initialMaxHeight = parseInt(content.dataset.initialMaxHeight || '200', 10);
                                if (content.scrollHeight > initialMaxHeight) {
                                    content.classList.add('has-overflow');
                                } else {
                                    content.classList.remove('has-overflow');
                                }
                            }

                            const pre = content.querySelector('pre.line-numbers');
                            if (pre && window.Prism && window.Prism.plugins && window.Prism.plugins.lineNumbers) {
                                window.Prism.plugins.lineNumbers.resize(pre);
                            }
                        });
                    }
                }
            } else if (target.classList.contains('copy-code-btn')) {
                Utils.copyToClipboard(codeText, target);
            } else if (target.classList.contains('download-code-btn')) {
                const filename = codeBlock.dataset.filename || 'code.txt';
                const language = codeBlock.dataset.language || 'plaintext';
                const extension = language === 'plaintext' ? 'txt' : language;
                const hasExtension = filename.toLowerCase().endsWith(`.${extension}`);
                const downloadName = hasExtension ? filename : `${filename}.${extension}`;
                const mimeType = language === 'svg' ? 'image/svg+xml' : `text/${language}`;
                Utils.downloadFile(codeText, downloadName, mimeType);
            } else if (target.classList.contains('toggle-code-btn')) {
                const content = codeBlock.querySelector('.code-block-content');
                if (!content) return;

                const iconExpand = target.querySelector('.icon-expand');
                const iconCollapse = target.querySelector('.icon-collapse');
                const isCurrentlyCollapsed = !content.classList.contains('expanded');

                if (isCurrentlyCollapsed) {
                    content.classList.add('expanded');
                    target.classList.add('expanded');
                    target.title = "Свернуть";
                    content.style.maxHeight = content.scrollHeight + "px";
                    if (iconExpand) iconExpand.style.display = 'none';
                    if (iconCollapse) iconCollapse.style.display = 'block';
                    content.classList.remove('has-overflow');
                    requestAnimationFrame(() => {
                        const pre = content.querySelector('pre.line-numbers');
                        if (pre && window.Prism && window.Prism.plugins && window.Prism.plugins.lineNumbers) {
                            window.Prism.plugins.lineNumbers.resize(pre);
                        }
                    });
                } else {
                    content.classList.remove('expanded');
                    target.classList.remove('expanded');
                    target.title = "Развернуть";
                    const initialMaxHeight = content.dataset.initialMaxHeight || '200px';
                    content.style.maxHeight = initialMaxHeight;
                    if (iconExpand) iconExpand.style.display = 'block';
                    if (iconCollapse) iconCollapse.style.display = 'none';
                    setTimeout(() => {
                        if (content.scrollHeight > parseInt(initialMaxHeight)) {
                            content.classList.add('has-overflow');
                        } else {
                            content.classList.remove('has-overflow');
                        }
                    }, 100);
                }
            }
        };

        const currentRef = contentRef.current;
        if (currentRef) {
            currentRef.addEventListener('click', handleClick);
            return () => {
                currentRef.removeEventListener('click', handleClick);
            };
        }
    }, [displayContent, markdownEnabledForMessage]);
    const handleCopy = async () => {
        const contentToCopy = isUser ? content : displayContent;
        if (!contentToCopy) return;
        try {
            await navigator.clipboard.writeText(contentToCopy);
        } catch (e) {
            console.error('Failed to copy', e);
        }
    };
    const handleSaveEdit = () => {
        if (editedContent.trim() !== content && editedContent.trim()) {
            onEdit(message.id, editedContent.trim());
        }
        setIsEditingUserMessage(false);
    };
    const handleCancelEdit = () => {
        setEditedContent(content);
        setIsEditingUserMessage(false);
    };
    const showUserActions = isUser && onEdit && !isLoading && !isEditingUserMessage;
    const messageClassName = cn(
        'message ui-message-shell',
        isUser ? 'user-message ui-message-shell-user' : 'ai-message ui-message-shell-ai',
        isLoading && 'loading',
        isError && 'error',
        showUserActions && 'has-user-actions'
    );
    const messageContentClassName = cn(
        'message-content ui-message-bubble',
        isUser ? 'ui-message-bubble-user' : 'ui-message-bubble-ai'
    );

    return (
        <div
            className={messageClassName}
            data-message-id={message.id}
            data-raw-content={isUser ? (content || '') : undefined}
        >
            <div className={messageContentClassName}>
                {displayImages?.length > 0 && (
                    <div
                        className={cn('message-image-grid', isUser ? 'user-image-grid' : 'ai-image-grid')}
                        data-count={displayImages.length}
                    >
                        {displayImages.map((src, idx) => {
                            const imagePath = typeof src === 'string' ? src : (src?.url_path || '');
                            if (!imagePath) {
                                return null;
                            }

                            const fullSrc = imagePath.startsWith('http')
                                ? imagePath
                                : `${apiService.baseURL}${imagePath}`;
                            return (
                                <MessageImageAttachment
                                    key={`${message.id}-image-${idx}`}
                                    src={fullSrc}
                                    alt={`Chat image ${idx + 1}`}
                                    messageId={message.id}
                                    isInteractive={!isUser}
                                />
                            );
                        })}
                    </div>
                )}

                {displayFiles?.length > 0 && (
                    <div
                        className={cn(
                            'message-attachments mt-2.5 flex flex-wrap gap-2',
                            isUser ? 'user-attachments' : 'ai-attachments'
                        )}
                    >
                        {displayFiles?.map((f, idx) => {
                            const file = f.file || f;
                            if (!file || typeof file === 'string' || (!file.url_path && !file.original_name && !file.name)) {
                                return null;
                            }

                            const fileName = file.original_name || file.name || 'File';
                            const fileUrl = file.url_path || '';
                            const fullUrl = fileUrl.startsWith('http') ? fileUrl : (fileUrl ? `${apiService.baseURL}${fileUrl}` : '');
                            const fileSize = file.size ? fileService.formatFileSize(file.size) : '';
                            const ext = fileName.split('.').pop()?.toLowerCase() || '';
                            const iconPath = fileService.getFileIconPath(ext);
                            const isImage = file.mime_type && fileService.VALID_IMAGE_MIME_TYPES.includes(file.mime_type) ||
                                          (ext && ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext));

                            return (
                                <div
                                    key={idx}
                                    className="attachment-file-card ui-attachment-card"
                                    title={`${fileName}${fileSize ? ` (${fileSize})` : ''}`}
                                >
                                    <div className="attachment-card-preview ui-attachment-preview">
                                        {isImage && fullUrl ? (
                                            <img
                                                src={fullUrl}
                                                alt={fileName}
                                                className="image-thumbnail h-full w-full object-cover"
                                                onClick={() => {
                                                    if (!isUser && window.openImageLightbox) {
                                                        window.openImageLightbox(fullUrl, message.id);
                                                    }
                                                }}
                                                style={{ cursor: !isUser ? 'pointer' : 'default' }}
                                                onError={(e) => {
                                                    e.currentTarget.src = iconPath;
                                                    e.currentTarget.className = 'generic-icon size-12 object-contain opacity-60';
                                                }}
                                            />
                                        ) : (
                                            <img
                                                src={iconPath}
                                                alt={fileName}
                                                className="generic-icon size-12 object-contain opacity-60"
                                                onError={(e) => {
                                                    e.currentTarget.src = 'https://cdn.jsdelivr.net/gh/vscode-icons/vscode-icons/icons/default_file.svg';
                                                }}
                                            />
                                        )}
                                    </div>
                                    <div className="attachment-card-footer ui-attachment-footer">
                                        <img
                                            src={iconPath}
                                            alt="icon"
                                            className="attachment-card-footer-icon"
                                            onError={(e) => {
                                                e.currentTarget.src = 'https://cdn.jsdelivr.net/gh/vscode-icons/vscode-icons/icons/default_file.svg';
                                            }}
                                        />
                                        <div className="attachment-card-footer-info">
                                            {fullUrl ? (
                                                <a
                                                    href={fullUrl}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className="file-card-name"
                                                    onClick={(e) => e.stopPropagation()}
                                                >
                                                    {fileName}
                                                </a>
                                            ) : (
                                                <span className="file-card-name">{fileName}</span>
                                            )}
                                            {fileSize && <span className="file-card-size">{fileSize}</span>}
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}

                {isGeneratingImage && (
                    <div className="image-generation-placeholder ui-message-image-placeholder">
                        <div className="image-placeholder-visual ui-message-image-visual">
                            <div className="shimmer-effect"></div>
                            <svg className="placeholder-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                                <polyline points="17 8 12 3 7 8"/>
                                <line x1="12" x2="12" y1="3" y2="15"/>
                            </svg>
                        </div>
                        <div className="image-placeholder-caption ui-message-image-caption">
                            Создание изображения: <span>"{imagePrompt || ''}"</span>
                        </div>
                    </div>
                )}

                {!isUser && isLoading && webSearchStatus && (
                    <WebSearchProgress status={webSearchStatus} t={t} />
                )}

                <div
                    ref={contentRef}
                    className="message-text ui-message-text"
                    dangerouslySetInnerHTML={{ __html: htmlContent }}
                />

                {widgets.map(widget => {
                    if (widget.type === 'quiz') {
                        return <Quiz key={widget.id} initialState={widget.state} />;
                    } else if (widget.type === 'spinwheel') {
                        return <Spinwheel key={widget.id} initialState={widget.state} />;
                    } else if (widget.type === 'beatbox') {
                        return <Beatbox key={widget.id} initialState={widget.state} />;
                    } else if (widget.type === 'think') {
                        return (
                            <ThinkBlock
                                key={widget.id}
                                content={widget.content}
                                openTime={widget.openTime}
                                closeTime={widget.closeTime}
                            />
                        );
                    }
                    return null;
                })}

                {isLoading && !displayContent && !isGeneratingImage && !webSearchStatus && (
                    <div className="live-thinking-animation ui-message-loader">
                        <div className="thinking-loader-wrapper">
                            <img src="/icons/load.svg" alt="Loading" className="thinking-loader-icon" />
                            <div className="thinking-phrase active">Думаю...</div>
                        </div>
                    </div>
                )}

                {!isUser && hasMultipleVariants && (
                    <div className="variants-nav ui-message-variants">
                        <button
                            type="button"
                            className={cn(
                                'variant-btn ui-message-variant-button prev-btn',
                                currentVariantIndex > 0 && 'active'
                            )}
                            title="Предыдущий ответ"
                            disabled={currentVariantIndex <= 0}
                            onClick={() => onSwitchVariant && onSwitchVariant(message.id, -1)}
                        >
                            <img src="/icons/media/prev.svg" alt="<" />
                        </button>
                        <span className="variants-counter ui-message-variant-counter">
                            {(currentVariantIndex || 0) + 1}/{variants.length}
                        </span>
                        <button
                            type="button"
                            className={cn(
                                'variant-btn ui-message-variant-button next-btn',
                                (currentVariantIndex || 0) < variants.length - 1 && 'active'
                            )}
                            title="Следующий ответ"
                            disabled={(currentVariantIndex || 0) >= variants.length - 1}
                            onClick={() => onSwitchVariant && onSwitchVariant(message.id, 1)}
                        >
                            <img src="/icons/media/next.svg" alt=">" />
                        </button>
                    </div>
                )}
                {!isUser && isLoading && displaySourceItems.length > 0 && (
                    <div className="actions-bar ui-message-actions">
                        <WebSourcesPanel sources={displaySourceItems} t={t} />
                    </div>
                )}
                {!isUser && !isLoading && (
                    <div className="actions-bar ui-message-actions">
                        <MessageActionButton
                            className="copy-md-btn"
                            title="Копировать"
                            onClick={handleCopy}
                        >
                            <img src="/icons/ui/copy.svg" alt="Copy" />
                        </MessageActionButton>
                        <MessageActionButton
                            className={cn(
                                'speak-btn',
                                audio.isVisible ? 'active' : '',
                                audio.isLoading ? 'loading' : '',
                                audio.isError ? 'error' : ''
                            )}
                            title="Озвучить"
                            onClick={() => {
                                if (displayContent) {
                                    audio.speak(displayContent);
                                }
                            }}
                        >
                            <img src="/icons/media/audio.svg" alt="Speak" />
                        </MessageActionButton>
                        {onRegenerate && (
                            <MessageActionButton
                                className="regenerate-btn"
                                title="Регенерировать"
                                onClick={() => onRegenerate(message.id)}
                            >
                                <img src="/icons/ui/regenerate.svg" alt="Regenerate" />
                            </MessageActionButton>
                        )}
                        <MessageActionButton
                            className="translate-btn"
                            title="Перевести"
                            onClick={() => {
                                const textToTranslate = contentRef.current?.textContent?.trim() || displayContent || '';
                                if (textToTranslate) {
                                    setShowTranslation(true);
                                } else {
                                    Utils.showPopupWarning?.('Нет текста для перевода.');
                                }
                            }}
                        >
                            <img src="/icons/ui/translate.svg" alt="Translate" />
                        </MessageActionButton>
                        <WebSourcesPanel sources={displaySourceItems} t={t} />
                    </div>
                )}
                {!isUser && showTranslation && (
                    <TranslationPanel
                        originalText={content || ''}
                        onClose={() => setShowTranslation(false)}
                    />
                )}
                {!isUser && audio.isVisible && (
                    <div className={cn('audio-player-container ui-audio-player visible', audio.isPlaying && 'playing')}>
                        <div className="audio-player-header ui-audio-player-header">
                            <div className="audio-player-icon ui-audio-player-icon">
                                <svg width="18" height="18" viewBox="0 0 24 24">
                                    <path d="M12 4V20M8 8V16M16 7V17M4 10V14M20 9V15" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                                </svg>
                                <span>Аудио</span>
                            </div>
                            {audio.isLoading && (
                                <div className="audio-player-loader">Загрузка аудио...</div>
                            )}
                        </div>
                        {!audio.isLoading && (
                            <div className="audio-player-controls ui-audio-player-controls">
                                <button
                                    type="button"
                                    className="audio-play-pause-btn ui-audio-play-button"
                                    title={audio.isPlaying ? "Пауза" : "Воспроизвести"}
                                    onClick={audio.togglePlayback}
                                >
                                    <svg className="play-pause-icon" width="18" height="18" viewBox="0 0 24 24">
                                        {audio.isPlaying ? (
                                            <path className="pause-icon" d="M8 5V19M16 5V19" stroke="currentColor" strokeWidth="2"/>
                                        ) : (
                                            <path className="play-icon" d="M5 3l14 9-14 9z" stroke="currentColor" strokeWidth="2" fill="currentColor"/>
                                        )}
                                    </svg>
                                </button>
                                <div className="audio-waveform-container ui-audio-waveform">
                                    <canvas ref={waveformCanvasRef} className="audio-waveform" height="48" width="200"></canvas>
                                    <input
                                        type="range"
                                        className="audio-progress-bar"
                                        min="0"
                                        max={audio.totalDuration || 1}
                                        value={audio.currentTime}
                                        step="0.1"
                                        onChange={(e) => audio.seekAudio(parseFloat(e.target.value))}
                                    />
                                </div>
                                <div className="audio-time ui-audio-time">
                                    {audio.formatTime(audio.currentTime)} / {audio.formatTime(audio.totalDuration)}
                                </div>
                            </div>
                        )}
                        {audio.isError && (
                            <div className="audio-error-message" style={{ display: 'block' }}>
                                Ошибка: Не удалось загрузить аудио.
                            </div>
                        )}
                    </div>
                )}
                {showUserActions && (
                    <div className="actions-bar ui-message-actions ui-user-message-actions">
                        <MessageActionButton
                            className="copy-btn"
                            title="Копировать"
                            onClick={handleCopy}
                        >
                            <img src="/icons/ui/copy.svg" alt="Copy" />
                        </MessageActionButton>
                        <MessageActionButton
                            className="edit-btn"
                            title="Редактировать"
                            onClick={() => setIsEditingUserMessage(true)}
                        >
                            <img src="/icons/ui/edit.svg" alt="Edit" />
                        </MessageActionButton>
                    </div>
                )}
                {isUser && isEditingUserMessage && (
                    <div className="user-message-edit-panel ui-edit-panel">
                        <textarea
                            className="user-message-edit-textarea ui-edit-textarea"
                            value={editedContent}
                            onChange={(e) => setEditedContent(e.target.value)}
                            placeholder="Отредактируйте ваше сообщение..."
                        />
                        <div className="edit-panel-buttons ui-edit-actions">
                            <button
                                type="button"
                                className="edit-save-btn ui-edit-save"
                                onClick={handleSaveEdit}
                                disabled={!editedContent.trim() || editedContent.trim() === content}
                            >
                                Сохранить
                            </button>
                            <button
                                type="button"
                                className="edit-cancel-btn ui-edit-cancel"
                                onClick={handleCancelEdit}
                            >
                                Отмена
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default Message;
