import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import Message from './Message';
import { useSettings } from '../../context/SettingsContext';

const ChatContainer = ({ history, isLoading, onRegenerate, onEdit, onSwitchVariant, currentSessionId = null, isReadOnly = false }) => {
    const containerRef = useRef<HTMLDivElement | null>(null);
    const chatEndRef = useRef<HTMLDivElement | null>(null);
    const { settings } = useSettings();
    const shouldAutoScrollRef = useRef(true);
    const { t } = useTranslation();
    useEffect(() => {
        const container = containerRef.current;
        const update = () => {
            const scrollTarget = container || document.documentElement;
            const distanceFromBottom = scrollTarget.scrollHeight - (scrollTarget.scrollTop + scrollTarget.clientHeight);
            shouldAutoScrollRef.current = distanceFromBottom < 200;
        };
        update();
        container?.addEventListener('scroll', update, { passive: true });
        window.visualViewport?.addEventListener('resize', update, { passive: true });
        return () => {
            container?.removeEventListener('scroll', update);
            window.visualViewport?.removeEventListener('resize', update);
        };
    }, []);
    useEffect(() => {
        if (!settings.autoscroll) return;
        const last = history[history.length - 1];
        const isUserJustSent = last && last.role === 'user';
        const shouldScroll = shouldAutoScrollRef.current || isUserJustSent || isLoading;
        const container = containerRef.current;
        if (shouldScroll && container) {
            container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
        } else if (shouldScroll && chatEndRef.current) {
            chatEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
        }
    }, [history, isLoading, settings.autoscroll]);

    return (
        <div
            ref={containerRef}
            className="chat-container ui-chat-stack"
            id="chatContainer"
            role="log"
            aria-live="polite"
            aria-relevant="additions text"
            aria-label={t('chat.ariaLog')}
        >
            {isReadOnly && (
                <div className="readonly-banner ui-notice-banner" role="status">
                    <span>{t('landing.readonlyBanner')}</span>
                </div>
            )}
            {history.map((msg) => (
                <Message
                    key={msg.id}
                    message={msg}
                    sessionId={currentSessionId}
                    onRegenerate={isReadOnly ? null : onRegenerate}
                    onEdit={isReadOnly ? null : onEdit}
                    onSwitchVariant={onSwitchVariant}
                />
            ))}
            <div ref={chatEndRef} className="clear-both float-left" />
        </div>
    );
};

export default ChatContainer;
