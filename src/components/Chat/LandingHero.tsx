import React, { useEffect, useState } from 'react';
import { formatPlainText, formatText } from '../../utils/formatting';
import { Utils } from '../../utils/utils';
import { useSettings } from '../../context/SettingsContext';
import { useTranslation } from 'react-i18next';
import { cn } from '../../utils/cn';

const LandingHero = ({ children, isReadOnly = false }) => {
    const [welcomeMessage, setWelcomeMessage] = useState(null);
    const [promptSuggestions, setPromptSuggestions] = useState([]);
    const { settings } = useSettings();
    const { t, i18n } = useTranslation();

    useEffect(() => {
        const messages = t('landing.welcomeMessages', { returnObjects: true });
        const list = Array.isArray(messages) ? messages : [messages].filter(Boolean);
        const fallback = list[0] || 'Welcome!';
        const message = Utils.getRandomPhrase(list.length > 0 ? list : [fallback], fallback);
        setWelcomeMessage(message);
    }, [i18n.resolvedLanguage]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        const loadPromptSuggestions = async () => {
            try {
                const response = await fetch('/images/prompts/prompts.json');
                if (!response.ok) throw new Error('Failed to fetch prompts');
                const data = await response.json();
                const prompts = data.prompts || [];
                setPromptSuggestions(prompts);
            } catch (error) {
                console.warn("Failed to load prompt suggestions:", error);
            }
        };
        if (settings.showSuggestions) {
            loadPromptSuggestions();
        }
    }, [settings.showSuggestions]);

    const handleSuggestionClick = (text) => {
        const input = document.getElementById('promptInput');
        if (input) {
            input.value = text;
            input.focus();
            input.dispatchEvent(new Event('input', { bubbles: true }));
        }
    };

    return (
        <section
            className="landing-hero ui-landing-shell"
            aria-label={t('landing.ariaLabel')}
        >
            {isReadOnly && (
                <div className="readonly-banner ui-notice-banner ui-landing-readonly">
                    <span>{t('landing.readonlyBanner')}</span>
                </div>
            )}

            {welcomeMessage && (
                <div
                    id="welcomeMessage"
                    className="welcome-message ui-landing-welcome"
                    dangerouslySetInnerHTML={{ __html: settings.renderMarkdown ? formatText(welcomeMessage) : formatPlainText(welcomeMessage) }}
                />
            )}

            <div className="landing-composer ui-landing-composer">
                {children}
            </div>

            {settings.showSuggestions && promptSuggestions.length > 0 && (
                <div
                    id="promptSuggestions"
                    className="prompt-suggestions ui-prompt-grid"
                >
                    {promptSuggestions.map((group, idx) => {
                        const randomText = Array.isArray(group.text)
                            ? group.text[Math.floor(Math.random() * group.text.length)]
                            : group.text;
                        return (
                            <button
                                key={idx}
                                className={cn('prompt-suggestion ui-prompt-card', 'max-sm:max-w-none')}
                                type="button"
                                onClick={() => handleSuggestionClick(randomText)}
                            >
                                <span className="suggestion-label ui-prompt-card-label">
                                    {group.label}
                                </span>
                            </button>
                        );
                    })}
                </div>
            )}
        </section>
    );
};

export default LandingHero;
