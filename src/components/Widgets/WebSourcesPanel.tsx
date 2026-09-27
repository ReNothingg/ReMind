import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
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

    const [open, setOpen] = useState(false);
    const [placement, setPlacement] = useState({ left: 12, edge: 12, width: 320, maxHeight: 280, above: false });
    const [preview, setPreview] = useState<{ source: NormalizedWebSource; rect: DOMRect } | null>(null);
    const anchorRef = useRef<HTMLDivElement>(null);
    const popupRef = useRef<HTMLDivElement>(null);
    const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const popupId = useId();
    const cancelClose = () => {
        if (closeTimer.current) clearTimeout(closeTimer.current);
        closeTimer.current = null;
    };
    const close = () => { setOpen(false); setPreview(null); };
    const scheduleClose = () => {
        cancelClose();
        closeTimer.current = setTimeout(() => {
            if (anchorRef.current?.contains(document.activeElement) || popupRef.current?.contains(document.activeElement)) return;
            close();
        }, 160);
    };
    useEffect(() => () => { if (closeTimer.current) clearTimeout(closeTimer.current); }, []);
    useLayoutEffect(() => {
        if (!open || mode !== 'popover') return;
        const position = () => {
            const anchor = anchorRef.current;
            if (!anchor) return;
            const rect = (anchor.closest('.actions-bar') || anchor).getBoundingClientRect();
            const viewport = window.visualViewport;
            const top = viewport?.offsetTop || 0;
            const height = viewport?.height || window.innerHeight;
            const bottom = top + height;
            if (rect.bottom <= top || rect.top >= bottom) { close(); return; }
            const width = Math.min(420, rect.width, window.innerWidth - 24);
            const aboveSpace = Math.max(0, rect.top - top - 20);
            const belowSpace = Math.max(0, bottom - rect.bottom - 20);
            const above = aboveSpace >= Math.min(280, belowSpace);
            setPlacement({
                left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
                edge: above ? window.innerHeight - rect.top + 8 : rect.bottom + 8,
                width, maxHeight: Math.min(280, above ? aboveSpace : belowSpace), above,
            });
            setPreview(null);
        };
        position();
        const onScroll = (event: Event) => { if (!popupRef.current?.contains(event.target as Node)) position(); };
        window.addEventListener('scroll', onScroll, true);
        window.addEventListener('resize', position);
        window.visualViewport?.addEventListener('resize', position);
        window.visualViewport?.addEventListener('scroll', position);
        const observer = new ResizeObserver(position);
        if (anchorRef.current) observer.observe(anchorRef.current.closest('.actions-bar') || anchorRef.current);
        const outside = (event: PointerEvent) => {
            if (!anchorRef.current?.contains(event.target as Node) && !popupRef.current?.contains(event.target as Node)) close();
        };
        const escape = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return;
            event.preventDefault();
            close();
            anchorRef.current?.querySelector('button')?.focus({ preventScroll: true });
        };
        document.addEventListener('pointerdown', outside);
        document.addEventListener('keydown', escape);
        return () => {
            window.removeEventListener('scroll', onScroll, true);
            window.removeEventListener('resize', position);
            window.visualViewport?.removeEventListener('resize', position);
            window.visualViewport?.removeEventListener('scroll', position);
            observer.disconnect();
            document.removeEventListener('pointerdown', outside);
            document.removeEventListener('keydown', escape);
        };
    }, [open, mode]);

    useEffect(() => {
        if (!preview || mode !== 'inline') return;
        const hide = () => setPreview(null);
        window.addEventListener('resize', hide);
        window.addEventListener('scroll', hide, true);
        return () => {
            window.removeEventListener('resize', hide);
            window.removeEventListener('scroll', hide, true);
        };
    }, [preview, mode]);

    if (normalizedSources.length === 0) return null;

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

        </>
    );

    const pills = normalizedSources.map((source, index) => (
        source.url ? (
            <a key={`${source.url}-${index}`} className="source-pill" href={source.url}
                target="_blank" rel="noopener noreferrer" aria-label={source.title}
                onPointerEnter={(event) => { if (event.pointerType !== 'touch') setPreview({ source, rect: event.currentTarget.getBoundingClientRect() }); }}
                onPointerLeave={() => setPreview(null)}
                onFocus={(event) => { setPreview({ source, rect: event.currentTarget.getBoundingClientRect() }); }}
                onBlur={() => setPreview(null)}>
                {renderPillContent(source)}
            </a>
        ) : <span key={`${source.title}-${index}`} className="source-pill">{renderPillContent(source)}</span>
    ));
    const previewAbove = preview ? preview.rect.top > 180 : false;
    return (
        <div ref={anchorRef}
            className={`web-sources-container ${mode === 'inline' ? 'is-inline' : ''} ${className}`.trim()}
            aria-label={t('webSearch.sourcesAria')}
            onPointerEnter={(event) => { cancelClose(); if (mode === 'popover' && event.pointerType !== 'touch') setOpen(true); }}
            onPointerLeave={scheduleClose} onBlur={scheduleClose}>
            {mode === 'popover' ? (
                <button type="button" className="web-sources-trigger" aria-expanded={open} aria-controls={popupId}
                    onClick={(event) => {
                        cancelClose(); setOpen((value) => !value); setPreview(null);
                        if (!open && event.detail === 0) requestAnimationFrame(() => popupRef.current?.querySelector('a')?.focus());
                    }}
                    onKeyDown={(event) => {
                        if (event.key !== 'ArrowDown') return;
                        event.preventDefault(); cancelClose(); setOpen(true);
                        requestAnimationFrame(() => popupRef.current?.querySelector('a')?.focus());
                    }}>
                    <img src="/icons/ui/web.svg" alt="" aria-hidden="true" />
                    <span>{t('webSearch.sourcesLabel')}</span>
                    <span className="web-sources-count">{normalizedSources.length}</span>
                </button>
            ) : <div className="web-sources-pills">{pills}</div>}
            {mode === 'popover' && open && createPortal(
                <div ref={popupRef} id={popupId} className="web-sources-pills web-sources-popover"
                    role="region" aria-label={t('webSearch.sourcesAria')}
                    style={{ left: placement.left, width: placement.width, maxHeight: placement.maxHeight,
                        top: placement.above ? 'auto' : placement.edge,
                        bottom: placement.above ? placement.edge : 'auto' }}
                    onPointerEnter={cancelClose} onPointerLeave={scheduleClose} onBlur={scheduleClose}
                    onScroll={() => setPreview(null)}>
                    {pills}
                </div>, document.body,
            )}
            {preview && (mode === 'inline' || open) && createPortal(
                <div className="source-tooltip source-viewport-tooltip" role="tooltip"
                    style={{ left: Math.max(12, Math.min(preview.rect.left, window.innerWidth - Math.min(320, window.innerWidth - 24) - 12)),
                        width: Math.min(320, window.innerWidth - 24),
                        top: previewAbove ? 'auto' : preview.rect.bottom + 6,
                        bottom: previewAbove ? window.innerHeight - preview.rect.top + 6 : 'auto',
                        maxHeight: Math.max(0, Math.min(160, previewAbove ? preview.rect.top - 18 : window.innerHeight - preview.rect.bottom - 18)) }}>
                    <strong>{preview.source.title}</strong>
                    {preview.source.snippet && <span>{preview.source.snippet}</span>}
                    {preview.source.displayUrl && <small>{preview.source.displayUrl}</small>}
                </div>, document.body,
            )}
        </div>
    );
}
