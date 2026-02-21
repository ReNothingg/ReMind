import React, { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import Message from './Message';
import { useSettings } from '../../context/SettingsContext';

const ChatContainer = ({ history, isLoading, onRegenerate, onEdit, onSwitchVariant, isReadOnly = false }) => {
    const chatEndRef = useRef(null);
    const { settings } = useSettings();
    const shouldAutoScrollRef = useRef(true);
    const { t } = useTranslation();
    useEffect(() => {
        const update = () => {
            const doc = document.documentElement;
            const distanceFromBottom = doc.scrollHeight - (window.scrollY + window.innerHeight);
            shouldAutoScrollRef.current = distanceFromBottom < 200;
        };
        update();
        window.addEventListener('scroll', update, { passive: true });
        return () => window.removeEventListener('scroll', update);
    }, []);
    useEffect(() => {
        if (!settings.autoscroll) return;
        const last = history[history.length - 1];
        const isUserJustSent = last && last.role === 'user';
        const shouldScroll = shouldAutoScrollRef.current || isUserJustSent || isLoading;
        if (shouldScroll && chatEndRef.current) {
            chatEndRef.current.scrollIntoView({ behavior: "smooth" });
        }
    }, [history, isLoading, settings.autoscroll]);

    return (
        <div className="chat-container" id="chatContainer">
            {isReadOnly && (
                <div className="readonly-banner">
                    <span>{t('landing.readonlyBanner')}</span>
                </div>
            )}
            {history.map((msg) => (
                <Message
                    key={msg.id}
                    message={msg}
                    onRegenerate={isReadOnly ? null : onRegenerate}
                    onEdit={isReadOnly ? null : onEdit}
                    onSwitchVariant={onSwitchVariant}
                />
            ))}
            <div ref={chatEndRef} style={{ float: "left", clear: "both" }} />
        </div>
    );
};

export default ChatContainer;
