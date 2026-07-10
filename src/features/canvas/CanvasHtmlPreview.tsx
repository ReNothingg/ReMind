import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';

type CanvasHtmlPreviewProps = {
    html: string;
};

const HTML_PREVIEW_FRAME_URL = '/html-preview.html';
const HTML_PREVIEW_MESSAGE_TYPE = 'remind:html-preview';

const CanvasHtmlPreview = ({ html }: CanvasHtmlPreviewProps) => {
    const { t } = useTranslation();
    const iframeRef = useRef<HTMLIFrameElement | null>(null);

    useEffect(() => {
        const iframe = iframeRef.current;
        if (!iframe) return;

        const renderPreview = () => {
            iframe.contentWindow?.postMessage({
                type: HTML_PREVIEW_MESSAGE_TYPE,
                html,
            }, '*');
        };

        iframe.addEventListener('load', renderPreview);
        if (iframe.dataset.previewReady === 'true') {
            renderPreview();
        } else {
            iframe.src = HTML_PREVIEW_FRAME_URL;
        }

        return () => iframe.removeEventListener('load', renderPreview);
    }, [html]);

    return (
        <section className="canvas-site-preview" aria-label={t('canvas.preview')}>
            <iframe
                ref={iframeRef}
                className="canvas-site-preview-frame"
                sandbox="allow-forms allow-scripts"
                title={t('canvas.preview')}
                onLoad={(event) => {
                    event.currentTarget.dataset.previewReady = 'true';
                }}
            />
        </section>
    );
};

export default CanvasHtmlPreview;
