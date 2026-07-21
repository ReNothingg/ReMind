import { useCallback, useEffect, useId, useState } from 'react';
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

type TranslationPanelProps = {
    originalText: string;
    onClose: () => void;
};

type TranslationResponse = {
    translated_text?: string;
    fallback?: boolean;
    error?: string;
    message?: string;
};

type TranslationError = Error & {
    status?: number;
    data?: { error?: string };
};

const TranslationPanel = ({ originalText, onClose }: TranslationPanelProps) => {
    const { t } = useTranslation();
    const fallbackTooltipId = useId();
    const [targetLang, setTargetLang] = useState('ru');
    const [translatedText, setTranslatedText] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [usedFallback, setUsedFallback] = useState(false);
    const [fallbackTooltipOpen, setFallbackTooltipOpen] = useState(false);

    const extractCleanText = (htmlText: string) => {
        if (!htmlText) return '';

        const tempDiv = document.createElement('div');
        DOMSafeUtils.setHTML(tempDiv, htmlText);
        const cleanText = tempDiv.textContent || tempDiv.innerText || '';
        return cleanText.trim();
    };

    const preserveTextFormatting = (text: string) => {
        if (!text) return '';

        let formattedText = text
            .replace(/\n/g, '<br>')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/`(.*?)`/g, '<code>$1</code>')
            .replace(
                /\[(.*?)\]\((.*?)\)/g,
                '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
            )
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

    const translateText = useCallback(
        async (text: string, lang: string) => {
            setIsLoading(true);
            setError(null);
            setTranslatedText(null);
            setUsedFallback(false);
            setFallbackTooltipOpen(false);

            try {
                const cleanText = extractCleanText(text);
                if (!cleanText) {
                    setError(t('translationPanel.noText'));
                    return;
                }

                const data = (await apiService.translate(
                    cleanText,
                    lang
                )) as TranslationResponse;

                if (!data?.translated_text) {
                    const errorMsg =
                        data?.error || data?.message || t('translationPanel.unknownError');
                    setError(t('translationPanel.errorPrefix', { message: errorMsg }));
                    return;
                }

                setUsedFallback(Boolean(data.fallback));
                setTranslatedText(preserveTextFormatting(data.translated_text));
            } catch (error) {
                console.error('Translation API error:', error);

                const typedError = error as TranslationError;
                let errorMessage = t('translationPanel.failed');
                let errorDetails = '';

                if (typedError.status === 500) {
                    errorMessage = t('translationPanel.serverErrorTitle');
                    errorDetails = t('translationPanel.serverErrorDetails');
                } else if (typedError.status === 404 || typedError.status === 503) {
                    errorMessage = t('translationPanel.serviceUnavailableTitle');
                    errorDetails = t('translationPanel.serviceUnavailableDetails');
                } else if (
                    typedError.status === 0 ||
                    typedError.message?.includes('Failed to fetch')
                ) {
                    errorMessage = t('translationPanel.noConnectionTitle');
                    errorDetails = t('translationPanel.noConnectionDetails');
                } else if (typedError.message) {
                    errorMessage = typedError.message;
                } else if (typedError.data?.error) {
                    errorMessage = typedError.data.error;
                }

                setError(errorMessage + (errorDetails ? `: ${errorDetails}` : ''));
            } finally {
                setIsLoading(false);
            }
        },
        [t]
    );

    useEffect(() => {
        if (originalText) {
            void translateText(originalText, targetLang);
        }
    }, [originalText, targetLang, translateText]);

    return (
        <div className="translation-panel active ui-inline-panel px-4 py-4 text-foreground">
            <div className="translation-header ui-panel-header">
                <div className="translation-header-controls">
                    <select
                        className="language-select ui-select-control"
                        value={targetLang}
                        onChange={(event) => setTargetLang(event.target.value)}
                        disabled={isLoading}
                        aria-label={t('translationPanel.translateAction')}
                    >
                        {LANGUAGE_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                                {t(`translationPanel.languages.${option.labelKey}`)}
                            </option>
                        ))}
                    </select>
                    {usedFallback && (
                        <span
                            className={`translation-fallback-info${fallbackTooltipOpen ? ' is-open' : ''}`}
                        >
                            <button
                                className="translation-fallback-trigger"
                                type="button"
                                aria-label={t('translationPanel.fallbackNotice')}
                                aria-describedby={fallbackTooltipId}
                                aria-expanded={fallbackTooltipOpen}
                                onClick={() => setFallbackTooltipOpen(true)}
                                onBlur={() => setFallbackTooltipOpen(false)}
                            >
                                !
                            </button>
                            <span
                                className="translation-fallback-tooltip"
                                id={fallbackTooltipId}
                                role="tooltip"
                            >
                                {t('translationPanel.fallbackNotice')}
                            </span>
                        </span>
                    )}
                </div>
                <button
                    className="translation-close-btn ui-icon-control ui-icon-dismiss size-9 rounded-md border-transparent bg-interactive text-muted hover:bg-surface-alt hover:text-foreground"
                    onClick={onClose}
                    aria-label={t('translationPanel.close')}
                    type="button"
                >
                    x
                </button>
            </div>

            <div className="translation-content ui-panel-body">
                <div className="text-column min-w-0 flex-1">
                    <div className="text-content translated-text ui-rich-panel ui-scrollbar-thin">
                        {isLoading && (
                            <div className="translation-loader ui-panel-loader">
                                <span className="size-4 animate-spin rounded-full border-2 border-[rgba(var(--color-white-raw),0.2)] border-t-accent-brand" />
                                <span>{t('translationPanel.loading')}</span>
                            </div>
                        )}
                        {error && <div className="translation-error ui-panel-error">{error}</div>}
                        {translatedText && !isLoading && !error && (
                            <div
                                dangerouslySetInnerHTML={{
                                    __html: sanitizeHtml(translatedText),
                                }}
                            />
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default TranslationPanel;
