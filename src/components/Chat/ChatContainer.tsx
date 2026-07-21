import { useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import Message from './Message';

const ChatContainer = ({
    history,
    isLoading,
    onRegenerate,
    onEdit,
    onSwitchVariant,
    onBeatboxStateChange,
    currentSessionId = null,
    isReadOnly = false
}) => {
    const containerRef = useRef<HTMLDivElement | null>(null);
    const chatEndRef = useRef<HTMLDivElement | null>(null);
    const shouldAutoScrollRef = useRef(true);
    const { t } = useTranslation();

    const getScrollTarget = useCallback(() => {
        const container = containerRef.current;
        if (container) {
            const { overflowY } = window.getComputedStyle(container);
            const isScrollable = /(auto|scroll)/.test(overflowY)
                && container.scrollHeight > container.clientHeight + 1;
            if (isScrollable) {
                return container;
            }
        }
        return document.scrollingElement || document.documentElement;
    }, []);

    useEffect(() => {
        const container = containerRef.current;
        const update = () => {
            const scrollTarget = getScrollTarget();
            const distanceFromBottom = scrollTarget.scrollHeight - (scrollTarget.scrollTop + scrollTarget.clientHeight);
            shouldAutoScrollRef.current = distanceFromBottom < 200;
        };
        update();
        container?.addEventListener('scroll', update, { passive: true });
        window.addEventListener('scroll', update, { passive: true });
        window.visualViewport?.addEventListener('resize', update, { passive: true });
        return () => {
            container?.removeEventListener('scroll', update);
            window.removeEventListener('scroll', update);
            window.visualViewport?.removeEventListener('resize', update);
        };
    }, [getScrollTarget]);
    useEffect(() => {
        const last = history[history.length - 1];
        const isUserJustSent = last && last.role === 'user';
        const shouldScroll = shouldAutoScrollRef.current || isUserJustSent || isLoading;
        if (shouldScroll) {
            const behavior: ScrollBehavior =
                typeof window.matchMedia === 'function'
                && window.matchMedia('(prefers-reduced-motion: reduce)').matches
                    ? 'auto'
                    : 'smooth';
            const scrollTarget = getScrollTarget();
            if (scrollTarget === containerRef.current) {
                scrollTarget.scrollTo({ top: scrollTarget.scrollHeight, behavior });
            } else if (chatEndRef.current) {
                chatEndRef.current.scrollIntoView({ behavior, block: 'end' });
            }
        }
    }, [getScrollTarget, history, isLoading]);

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
            <div className="chat-container-content">
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
                        onBeatboxStateChange={onBeatboxStateChange}
                    />
                ))}
                <div ref={chatEndRef} className="clear-both float-left" />
            </div>
        </div>
    );
};

export default ChatContainer;
