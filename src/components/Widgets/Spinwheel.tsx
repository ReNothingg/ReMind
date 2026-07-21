import { useCallback, useRef, useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { buildSpinwheelSegments, normalizeSpinwheelConfig } from './spinwheelConfig';

const Spinwheel = ({ initialState }) => {
    const { t } = useTranslation();
    const config = useMemo(() => normalizeSpinwheelConfig(initialState), [initialState]);

    const reelRef = useRef(null);
    const animationFrameRef = useRef(null);
    const finishTimerRef = useRef(null);
    const currentIndexRef = useRef(0);
    const [isSpinning, setIsSpinning] = useState(false);
    const [hasSpun, setHasSpun] = useState(false);
    const segments = useMemo(() => buildSpinwheelSegments(config), [config]);
    const displaySegments = useMemo(
        () => [...segments, ...segments, ...segments, ...segments, ...segments],
        [segments]
    );
    const resolvedTarget = segments.reduce((nearest, value) =>
        Math.abs(value - config.target) < Math.abs(nearest - config.target) ? value : nearest
    );

    const positionReel = useCallback((index) => {
        const reel = reelRef.current;
        const viewport = reel?.parentElement;
        const targetItem = reel?.children[index];
        if (!reel || !viewport || !targetItem) return;

        const viewportRect = viewport.getBoundingClientRect();
        const targetRect = targetItem.getBoundingClientRect();
        const computedTransform = window.getComputedStyle(reel).transform;
        const currentOffset = computedTransform === 'none'
            ? 0
            : new DOMMatrixReadOnly(computedTransform).m42;
        const centerDelta = viewportRect.top + viewportRect.height / 2
            - (targetRect.top + targetRect.height / 2);
        const offset = currentOffset + centerDelta;
        currentIndexRef.current = index;
        reel.style.transform = `translateY(${offset}px)`;
    }, []);

    const spin = () => {
        if (isSpinning || hasSpun || resolvedTarget === undefined) return;
        setIsSpinning(true);
        setHasSpun(true);

        const targetIndex = segments.indexOf(resolvedTarget);
        const middleOffset = segments.length * 2;
        const finalIndex = middleOffset + targetIndex;
        const startIndex = finalIndex - segments.length * 2;
        const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        const duration = reduceMotion ? 0 : Math.max(0, Number(config.spinTime) || 0);

        if (reelRef.current) {
            reelRef.current.style.transition = 'none';
            positionReel(startIndex);
            reelRef.current.getBoundingClientRect();

            animationFrameRef.current = window.requestAnimationFrame(() => {
                if (!reelRef.current) return;
                reelRef.current.style.transition = duration > 0
                    ? `transform ${duration}ms cubic-bezier(0.25, 1, 0.5, 1)`
                    : 'none';
                positionReel(finalIndex);
            });
        }

        finishTimerRef.current = window.setTimeout(() => {
            setIsSpinning(false);
        }, duration);
    };

    useEffect(() => {
        if(reelRef.current && !hasSpun) {
             const startIdx = segments.indexOf(config.min);
             const initialIndex = segments.length * 2 + Math.max(0, startIdx);
             positionReel(initialIndex);
        }
    }, [config.min, hasSpun, positionReel, segments]);

    useEffect(() => {
        const viewport = reelRef.current?.parentElement;
        if (!viewport || typeof ResizeObserver === 'undefined') return undefined;

        const observer = new ResizeObserver(() => {
            if (!reelRef.current) return;
            reelRef.current.style.transition = 'none';
            positionReel(currentIndexRef.current);
        });
        observer.observe(viewport);
        return () => observer.disconnect();
    }, [positionReel]);

    useEffect(() => () => {
        if (animationFrameRef.current !== null) {
            window.cancelAnimationFrame(animationFrameRef.current);
        }
        if (finishTimerRef.current !== null) {
            window.clearTimeout(finishTimerRef.current);
        }
    }, []);

    const statusText = isSpinning
        ? t('spinwheel.spinning')
        : hasSpun && resolvedTarget !== undefined
            ? t('spinwheel.result', { value: resolvedTarget })
            : '';

    return (
        <div className={`spin-wheel-container ${isSpinning ? 'spinning' : ''}`} aria-busy={isSpinning}>
            <div className="wheel-viewport" aria-hidden="true">
                <ul className="wheel-reel" ref={reelRef}>
                    {displaySegments.map((num, i) => (
                        <li key={i} className={(!isSpinning && hasSpun && num === resolvedTarget) ? 'active' : ''}>
                            {num}
                        </li>
                    ))}
                </ul>
            </div>
            <div className="controls">
                {!hasSpun && (
                    <button type="button" className="spin-button" onClick={spin}>{t('spinwheel.spin')}</button>
                )}
            </div>
            <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">{statusText}</p>
        </div>
    );
};

export default Spinwheel;
