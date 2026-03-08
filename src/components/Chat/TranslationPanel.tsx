import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { apiService } from '../../services/api';
import { DOMSafeUtils } from '../../utils/dom-safe';
import { sanitizeHtml } from '../../utils/sanitizeHtml';

const LANGUAGE_OPTIONS = [
    { value: 'en', labelKey: 'english' },
    { value: 'ru', labelKey: 'russian' },
    { value: 'es', labelKey: 'spanish' },
    { value: 'de', labelKey: 'german' },
    { value: 'fr', labelKey: 'french' },
    { value: 'zh-CN', labelKey: 'chinese' },
    { value: 'ja', labelKey: 'japanese' },
    { value: 'ko', labelKey: 'korean' },
    { value: 'it', labelKey: 'italian' },
    { value: 'pt', labelKey: 'portuguese' },
    { value: 'ar', labelKey: 'arabic' },
    { value: 'hi', labelKey: 'hindi' },
    { value: 'bn', labelKey: 'bengali' },
];

const TranslationPanel = ({ originalText, onClose }) => {
    const { t } = useTranslation();
    const [targetLang, setTargetLang] = useState('ru');
    const [translatedText, setTranslatedText] = useState(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    useEffect(() => {
        if (originalText) {
            translateText(originalText, targetLang);
        }
    }, [targetLang, originalText]); // eslint-disable-line react-hooks/exhaustive-deps

    const extractCleanText = (htmlText) => {
        if (!htmlText) return '';
        const tempDiv = document.createElement('div');
        DOMSafeUtils.setHTML(tempDiv, htmlText);
        const cleanText = tempDiv.textContent || tempDiv.innerText || '';
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
                        <div class="translation-fallback-notice ui-inline-notice">
                            <span class="fallback-icon">вљ пёЏ</span>
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
            console.error('Translation API error:', err);
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

    return (
        <div className="translation-panel active ui-inline-panel px-4 py-4 text-foreground shadow-[var(--shadow-sm)]">
            <div className="translation-header ui-panel-header">
                <select
                    className="language-select ui-select-control"
                    value={targetLang}
                    onChange={(e) => setTargetLang(e.target.value)}
                    disabled={isLoading}
                >
                    {LANGUAGE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                            {t(`translationPanel.languages.${option.labelKey}`)}
                        </option>
                    ))}
                </select>
                <button
                    className="translation-close-btn ui-icon-control ui-icon-dismiss size-9 rounded-lg border-transparent bg-interactive text-muted hover:bg-surface-alt hover:text-foreground"
                    onClick={onClose}
                    aria-label={t('translationPanel.close')}
                    type="button"
                >
                    Г—
                </button>
            </div>

            <div className="translation-content ui-panel-body">
                <div className="text-column min-w-0 flex-1">
                    <div
                        className="text-content translated-text ui-rich-panel ui-scrollbar-thin"
                    >
                        {isLoading && (
                            <div className="translation-loader ui-panel-loader">
                                <span className="size-4 animate-spin rounded-full border-2 border-[rgba(var(--color-white-raw),0.2)] border-t-accent-brand" />
                                <span>{t('translationPanel.loading')}</span>
                            </div>
                        )}
                        {error && (
                            <div className="translation-error ui-panel-error">
                                {error}
                            </div>
                        )}
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
