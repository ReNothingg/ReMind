import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { sanitizeHtml } from '../../utils/sanitizeHtml';
import { cn } from '../../utils/cn';

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
        <div className="think-block-wrapper mb-4 overflow-hidden rounded-lg border border-border-strong bg-surface-alt">
            <div className="think-block-header flex cursor-pointer items-center gap-3 border-b border-border-strong bg-interactive px-4 py-3 transition-colors duration-200 hover:border-border-heavy">
                <button
                    className="think-block-toggle inline-flex size-8 items-center justify-center rounded-sm p-0 text-accent-brand transition duration-200 hover:text-foreground active:scale-95"
                    onClick={() => setIsExpanded(!isExpanded)}
                    aria-expanded={isExpanded}
                    aria-label={isExpanded ? t('think.collapse') : t('think.expand')}
                >
                    <svg
                        className={cn(
                            'think-block-icon size-5 transition-transform duration-300',
                            isExpanded && 'expanded rotate-180'
                        )}
                        viewBox="0 0 24 24"
                        fill="currentColor"
                        width="20"
                        height="20"
                    >
                        <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z" />
                    </svg>
                </button>
                <div className="think-block-label flex-1 text-sm font-semibold text-accent-brand">{t('think.label')}</div>
                <div className="think-block-timer whitespace-nowrap rounded-sm border border-border bg-[rgba(var(--color-accent-raw),0.08)] px-2 py-1 font-mono text-xs text-subtle">
                    {formatTime(thinkingTime)}
                </div>
            </div>
            {isExpanded && (
                <div className="think-block-content px-4 py-4 text-sm leading-6 text-foreground">
                    <div dangerouslySetInnerHTML={{ __html: sanitizeHtml(content) }} />
                </div>
            )}
        </div>
    );
};

export default ThinkBlock;
