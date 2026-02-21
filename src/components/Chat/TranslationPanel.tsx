import React, { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { apiService } from '../../services/api';
import { DOMSafeUtils } from '../../utils/dom-safe';
import { sanitizeHtml } from '../../utils/sanitizeHtml';

const TranslationPanel = ({ originalText, onClose }) => {
    const { t } = useTranslation();
    const [targetLang, setTargetLang] = useState('ru');
    const [translatedText, setTranslatedText] = useState(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    const [isActive, setIsActive] = useState(true);
    const panelRef = useRef(null);

    useEffect(() => {
        if (isActive && originalText) {
            translateText(originalText, targetLang);
        }
    }, [targetLang, isActive]);

    const extractCleanText = (htmlText) => {
        if (!htmlText) return '';
        const tempDiv = document.createElement('div');
        DOMSafeUtils.setHTML(tempDiv, htmlText);
        let cleanText = tempDiv.textContent || tempDiv.innerText || '';
        return cleanText.trim();
    };

    const preserveTextFormatting = (text) => {
        if (!text) return '';
        let formattedText = text
            .replace(/\n/g, '<br>')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/`(.*?)`/g, '<code>$1</code>')
            .replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
            .replace(/^>\s*(.*)/gm, '<blockquote>$1</blockquote>')
            .replace(/^[-*+]\s+(.*)/gm, '<li>$1</li>')
            .replace(/^(\d+)\.\s+(.*)/gm, '<li>$2</li>');

        if (formattedText.includes('<li>')) {
            if (formattedText.match(/^\d+\./m)) {
                formattedText = formattedText.replace(/(<li>.*<\/li>)/s, '<ol>$1</ol>');
            } else {
                formattedText = formattedText.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
            }
        }
        return formattedText;
    };

    const translateText = async (text, lang) => {
        setIsLoading(true);
        setError(null);
        setTranslatedText(null);

        try {
            const cleanText = extractCleanText(text);
            if (!cleanText || cleanText.trim().length === 0) {
                setError(t('translationPanel.noText'));
                setIsLoading(false);
                return;
            }

            const data = await apiService.translate(cleanText, lang);
            if (data?.translated_text) {
                let translatedContent = preserveTextFormatting(data.translated_text);
                if (data.fallback) {
                    translatedContent = `
                        <div class="translation-fallback-notice">
                            <span class="fallback-icon">⚠️</span>
                            ${t('translationPanel.fallbackNotice')}
                        </div>
                        ${translatedContent}
                    `;
                }
                setTranslatedText(translatedContent);
            } else {
                const errorMsg = data?.error || data?.message || t('translationPanel.unknownError');
                setError(t('translationPanel.errorPrefix', { message: errorMsg }));
            }
        } catch (err) {
            console.error("Translation API error:", err);
            let errorMessage = t('translationPanel.failed');
            let errorDetails = '';

            if (err.status === 500) {
                errorMessage = t('translationPanel.serverErrorTitle');
                errorDetails = t('translationPanel.serverErrorDetails');
            } else if (err.status === 404) {
                errorMessage = t('translationPanel.serviceUnavailableTitle');
                errorDetails = t('translationPanel.serviceUnavailableDetails');
            } else if (err.status === 0 || err.message?.includes('Failed to fetch')) {
                errorMessage = t('translationPanel.noConnectionTitle');
                errorDetails = t('translationPanel.noConnectionDetails');
            } else if (err.message) {
                errorMessage = err.message;
            } else if (err.data?.error) {
                errorMessage = err.data.error;
            }

            setError(errorMessage + (errorDetails ? `: ${errorDetails}` : ''));
        } finally {
            setIsLoading(false);
        }
    };

    if (!isActive) return null;

    return (
        <div ref={panelRef} className="translation-panel active">
            <div className="translation-header">
                <select
                    className="language-select"
                    value={targetLang}
                    onChange={(e) => setTargetLang(e.target.value)}
                    disabled={isLoading}
                >
                    <option value="en">{t('translationPanel.languages.english')}</option>
                    <option value="ru">{t('translationPanel.languages.russian')}</option>
                    <option value="es">{t('translationPanel.languages.spanish')}</option>
                    <option value="de">{t('translationPanel.languages.german')}</option>
                    <option value="fr">{t('translationPanel.languages.french')}</option>
                    <option value="zh-CN">{t('translationPanel.languages.chinese')}</option>
                    <option value="ja">{t('translationPanel.languages.japanese')}</option>
                    <option value="ko">{t('translationPanel.languages.korean')}</option>
                    <option value="it">{t('translationPanel.languages.italian')}</option>
                    <option value="pt">{t('translationPanel.languages.portuguese')}</option>
                    <option value="ar">{t('translationPanel.languages.arabic')}</option>
                    <option value="hi">{t('translationPanel.languages.hindi')}</option>
                    <option value="bn">{t('translationPanel.languages.bengali')}</option>
                </select>
                <button className="translation-close-btn" onClick={onClose} aria-label={t('translationPanel.close')}>
                    ×
                </button>
            </div>
            <div className="translation-content">
                <div className="text-column">
                    <div className="text-content translated-text">
                        {isLoading && <div className="translation-loader">{t('translationPanel.loading')}</div>}
                        {error && <div className="translation-error">{error}</div>}
                        {translatedText && !isLoading && !error && (
                            <div dangerouslySetInnerHTML={{ __html: sanitizeHtml(translatedText) }} />
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default TranslationPanel;
