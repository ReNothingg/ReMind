import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ModalShell from '../UI/ModalShell';

const HtmlPreviewModal = ({ isOpen, onClose, urlOrHtml, isHtml = false }) => {
    const [isLoading, setIsLoading] = useState(true);
    const { t } = useTranslation();
    const iframeRef = useRef(null);

    useEffect(() => {
        if (!isOpen) return;

        const iframe = iframeRef.current;
        if (!iframe) return;

        setIsLoading(true);

        if (isHtml) {
            try {
                iframe.srcdoc = urlOrHtml || '';
            } catch (_err) {
                const blob = new Blob([urlOrHtml || ''], { type: 'text/html' });
                iframe.src = URL.createObjectURL(blob);
            }
        } else {
            iframe.src = urlOrHtml || 'about:blank';
        }

        const handleLoad = () => setIsLoading(false);
        const handleError = () => setTimeout(() => setIsLoading(false), 300);

        iframe.addEventListener('load', handleLoad);
        iframe.addEventListener('error', handleError);

        return () => {
            iframe.removeEventListener('load', handleLoad);
            iframe.removeEventListener('error', handleError);
        };
    }, [isOpen, urlOrHtml, isHtml]);

    useEffect(() => {
        if (!isOpen) return;

        const handleEscape = (e) => {
            if (e.key === 'Escape') {
                onClose();
            }
        };

        document.addEventListener('keydown', handleEscape);

        return () => {
            document.removeEventListener('keydown', handleEscape);
        };
    }, [isOpen, onClose]);

    useEffect(() => {
        if (isOpen) {
            document.body.classList.add('html-preview-blur');
        } else {
            document.body.classList.remove('html-preview-blur');
            setTimeout(() => {
                if (iframeRef.current) {
                    try {
                        iframeRef.current.srcdoc = '';
                    } catch (_err) {
                    }
                    iframeRef.current.src = 'about:blank';
                }
            }, 200);
        }

        return () => {
            document.body.classList.remove('html-preview-blur');
        };
    }, [isOpen]);

    if (!isOpen) return null;

    return (
        <ModalShell
            className="html-preview-modal px-2 py-3 sm:px-4 sm:py-6"
            contentClassName="html-preview-content relative h-[min(92vh,860px)] w-full max-w-6xl rounded-[18px] border-border bg-surface shadow-[var(--shadow-xl)]"
            onBackdropClick={onClose}
        >
            <button
                className="html-preview-close-btn ui-icon-control absolute right-4 top-4 z-10 size-10 rounded-xl border-transparent bg-interactive text-muted hover:bg-surface-alt hover:text-foreground"
                onClick={onClose}
                title={t('common.closeEsc')}
                type="button"
            >
                Г—
            </button>
            <div id="htmlPreviewFrameWrap" className="h-full w-full overflow-hidden rounded-[inherit]">
                {isLoading && (
                    <div
                        id="htmlPreviewLoading"
                        className="html-preview-loading absolute inset-0 z-[1] flex items-center justify-center bg-overlay/70 text-sm font-medium text-foreground"
                    >
                        {t('common.loading')}
                    </div>
                )}
                <iframe
                    ref={iframeRef}
                    className="block h-full w-full border-0"
                    sandbox="allow-forms"
                    title="HTML Preview"
                />
            </div>
        </ModalShell>
    );
};

export default HtmlPreviewModal;
