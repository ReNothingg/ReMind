import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../utils/cn';

const SHOW_DISTANCE_PX = 360;
const SETTLE_DELAY_MS = 140;

function getScrollTarget(): HTMLElement {
    const container = document.getElementById('chatContainer');
    if (container) {
        const { overflowY } = window.getComputedStyle(container);
        const isScrollable = /(auto|scroll)/.test(overflowY)
            && container.scrollHeight > container.clientHeight + 1;
        if (isScrollable) return container;
    }
    return (document.scrollingElement as HTMLElement | null) || document.documentElement;
}

function prefersReducedMotion() {
    return typeof window.matchMedia === 'function'
        && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

const ScrollToLatestButton = () => {
    const { t } = useTranslation();
    const [isVisible, setIsVisible] = useState(false);
    const settleTimerRef = useRef<number | null>(null);

    useEffect(() => {
        const evaluate = () => {
            const target = getScrollTarget();
            const distance = target.scrollHeight - (target.scrollTop + target.clientHeight);
            return distance > SHOW_DISTANCE_PX;
        };

        // Hide immediately when the reader reaches the end; show only after scrolling
        // settles so programmatic smooth scrolls to the bottom never flash the button.
        const update = () => {
            if (settleTimerRef.current !== null) {
                window.clearTimeout(settleTimerRef.current);
                settleTimerRef.current = null;
            }
            if (!evaluate()) {
                setIsVisible(false);
                return;
            }
            settleTimerRef.current = window.setTimeout(() => {
                settleTimerRef.current = null;
                setIsVisible(evaluate());
            }, SETTLE_DELAY_MS);
        };

        const container = document.getElementById('chatContainer');
        const resizeObserver = typeof ResizeObserver === 'function' && container
            ? new ResizeObserver(update)
            : null;

        update();
        window.addEventListener('scroll', update, { passive: true });
        container?.addEventListener('scroll', update, { passive: true });
        window.visualViewport?.addEventListener('resize', update, { passive: true });
        if (container) resizeObserver?.observe(container);

        return () => {
            if (settleTimerRef.current !== null) window.clearTimeout(settleTimerRef.current);
            window.removeEventListener('scroll', update);
            container?.removeEventListener('scroll', update);
            window.visualViewport?.removeEventListener('resize', update);
            resizeObserver?.disconnect();
        };
    }, []);

    const scrollToLatest = useCallback(() => {
        const target = getScrollTarget();
        target.scrollTo({
            top: target.scrollHeight,
            behavior: prefersReducedMotion() ? 'auto' : 'smooth',
        });
    }, []);

    const label = t('chat.scrollToLatest');

    return (
        <button
            type="button"
            className={cn('chat-scroll-latest', isVisible && 'is-visible')}
            onClick={scrollToLatest}
            aria-label={label}
            title={label}
            aria-hidden={!isVisible}
            tabIndex={isVisible ? 0 : -1}
            inert={!isVisible}
        >
            <ArrowDown size={18} strokeWidth={2} aria-hidden="true" />
        </button>
    );
};

export default ScrollToLatestButton;
