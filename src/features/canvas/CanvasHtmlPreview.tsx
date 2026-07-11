import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef } from 'react';
import { useTranslation } from 'react-i18next';

type CanvasHtmlPreviewProps = {
    html: string;
};

export type CanvasHtmlPreviewHandle = {
    render: (html: string) => void;
};

const HTML_PREVIEW_FRAME_URL = '/html-preview.html';
const HTML_PREVIEW_MESSAGE_TYPE = 'remind:html-preview';

const CanvasHtmlPreview = forwardRef<CanvasHtmlPreviewHandle, CanvasHtmlPreviewProps>(({ html }, ref) => {
    const { t } = useTranslation();
    const iframeRef = useRef<HTMLIFrameElement | null>(null);
    const latestHtmlRef = useRef(html);
    const renderTimerRef = useRef<number | null>(null);

    const postPreview = useCallback((nextHtml: string) => {
        latestHtmlRef.current = nextHtml;
        const iframe = iframeRef.current;
        if (!iframe || iframe.dataset.previewReady !== 'true') return;
        iframe.contentWindow?.postMessage({
            type: HTML_PREVIEW_MESSAGE_TYPE,
            html: nextHtml,
        }, '*');
    }, []);

    const renderPreview = useCallback((nextHtml: string) => {
        latestHtmlRef.current = nextHtml;
        if (renderTimerRef.current !== null) {
            window.clearTimeout(renderTimerRef.current);
        }
        renderTimerRef.current = window.setTimeout(() => {
            renderTimerRef.current = null;
            postPreview(latestHtmlRef.current);
        }, 90);
    }, [postPreview]);

    useImperativeHandle(ref, () => ({ render: renderPreview }), [renderPreview]);

    useEffect(() => {
        const iframe = iframeRef.current;
        if (!iframe) return;

        const handleLoad = () => {
            iframe.dataset.previewReady = 'true';
            postPreview(latestHtmlRef.current);
        };

        iframe.addEventListener('load', handleLoad);
        if (iframe.dataset.previewReady === 'true') {
            postPreview(html);
        } else {
            iframe.src = HTML_PREVIEW_FRAME_URL;
        }

        return () => iframe.removeEventListener('load', handleLoad);
    }, [html, postPreview]);

    useEffect(() => () => {
        if (renderTimerRef.current !== null) {
            window.clearTimeout(renderTimerRef.current);
        }
    }, []);

    return (
        <section className="canvas-site-preview" aria-label={t('canvas.preview')}>
            <iframe
                ref={iframeRef}
                className="canvas-site-preview-frame"
                sandbox="allow-scripts"
                title={t('canvas.preview')}
            />
        </section>
    );
});

CanvasHtmlPreview.displayName = 'CanvasHtmlPreview';

export default CanvasHtmlPreview;
