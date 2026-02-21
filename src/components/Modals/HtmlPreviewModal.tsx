import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { DOMSafeUtils } from '../../utils/dom-safe';

const HtmlPreviewModal = ({ isOpen, onClose, urlOrHtml, isHtml = false }) => {
    const [isLoading, setIsLoading] = useState(true);
    const { t } = useTranslation();
    const iframeRef = useRef(null);
    const modalRef = useRef(null);
    const overlayRef = useRef(null);

    useEffect(() => {
        if (!isOpen) return;

        const iframe = iframeRef.current;
        if (!iframe) return;

        setIsLoading(true);

        if (isHtml) {
            try {
                iframe.srcdoc = urlOrHtml || '';
            } catch (e) {
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

        const handleClickOutside = (e) => {
            if (modalRef.current && !modalRef.current.contains(e.target) && overlayRef.current?.contains(e.target)) {
                onClose();
            }
        };

        document.addEventListener('keydown', handleEscape);
        document.addEventListener('click', handleClickOutside);

        return () => {
            document.removeEventListener('keydown', handleEscape);
            document.removeEventListener('click', handleClickOutside);
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
                    } catch (e) {
                    }
                    iframeRef.current.src = 'about:blank';
                }
            }, 200);
        }
    }, [isOpen]);

    if (!isOpen) return null;

    return (
        <div className="html-preview-modal" ref={modalRef}>
            <div className="html-preview-modal__overlay" ref={overlayRef}></div>
            <div className="html-preview-content">
                <button className="html-preview-close-btn" onClick={onClose} title={t('common.closeEsc')}>
                    ×
                </button>
                <div id="htmlPreviewFrameWrap" style={{ width: '100%', height: '100%', position: 'relative' }}>
                    {isLoading && (
                        <div id="htmlPreviewLoading" className="html-preview-loading">
                            {t('common.loading')}
                        </div>
                    )}
                    <iframe
                        ref={iframeRef}
                        style={{
                            width: '100%',
                            height: '100%',
                            border: 'none',
                            display: 'block'
                        }}
                        sandbox="allow-forms"
                        title="HTML Preview"
                    />
                </div>
            </div>
        </div>
    );
};

export default HtmlPreviewModal;

