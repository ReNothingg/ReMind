import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import '../../styles/components/chat/think-block.css';
import { sanitizeHtml } from '../../utils/sanitizeHtml';

const ThinkBlock = ({ content, openTime, closeTime }) => {
    const [isExpanded, setIsExpanded] = useState(false);
    const { t } = useTranslation();
    const thinkingTime = React.useMemo(() => {
        if (openTime && closeTime) {
            return closeTime - openTime;
        }
        return 0;
    }, [openTime, closeTime]);
    const formatTime = (ms) => {
        if (ms < 1000) {
            return `${ms}ms`;
        }
        return `${(ms / 1000).toFixed(2)}s`;
    };

    if (!content) {
        return null;
    }

    return (
        <div className="think-block-wrapper">
            <div className="think-block-header">
                <button
                    className="think-block-toggle"
                    onClick={() => setIsExpanded(!isExpanded)}
                    aria-expanded={isExpanded}
                    aria-label={isExpanded ? t('think.collapse') : t('think.expand')}
                >
                    <svg
                        className={`think-block-icon ${isExpanded ? 'expanded' : ''}`}
                        viewBox="0 0 24 24"
                        fill="currentColor"
                        width="20"
                        height="20"
                    >
                        <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z" />
                    </svg>
                </button>
                <div className="think-block-label">{t('think.label')}</div>
                <div className="think-block-timer">
                    {formatTime(thinkingTime)}
                </div>
            </div>
            {isExpanded && (
                <div className="think-block-content">
                    <div dangerouslySetInnerHTML={{ __html: sanitizeHtml(content) }} />
                </div>
            )}
        </div>
    );
};

export default ThinkBlock;
