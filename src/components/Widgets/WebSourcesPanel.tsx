import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
    normalizeWebSources,
    sourceFallbackIcon,
    type NormalizedWebSource,
    type RawWebSource,
} from './webSources';

type WebSourcesPanelProps = {
    sources?: RawWebSource[];
    className?: string;
    mode?: 'popover' | 'inline';
};

export default function WebSourcesPanel({
    sources,
    className = '',
    mode = 'popover',
}: WebSourcesPanelProps) {
    const { t } = useTranslation();
    const normalizedSources = useMemo(
        () => normalizeWebSources(sources, t('webSearch.sourceFallback')),
        [sources, t],
    );

    if (normalizedSources.length === 0) {
        return null;
    }

    const renderPillContent = (source: NormalizedWebSource) => (
        <>
            <span className="source-pill-icon-wrap" aria-hidden="true">
                <img
                    className={`source-favicon ${source.faviconUrl === sourceFallbackIcon ? 'is-fallback' : ''}`.trim()}
                    src={source.faviconUrl}
                    alt=""
                    loading="lazy"
                    onError={(event) => {
                        if (event.currentTarget.dataset.fallbackApplied !== 'true') {
                            event.currentTarget.dataset.fallbackApplied = 'true';
                            event.currentTarget.classList.add('is-fallback');
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
        <div
            className={`web-sources-container ${mode === 'inline' ? 'is-inline' : ''} ${className}`.trim()}
            aria-label={t('webSearch.sourcesAria')}
        >
            {mode === 'popover' && (
                <div className="web-sources-trigger">
                    <img src="/icons/ui/web.svg" alt="" aria-hidden="true" />
                    <span>{t('webSearch.sourcesLabel')}</span>
                    <span className="web-sources-count">{normalizedSources.length}</span>
                </div>
            )}
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
}
