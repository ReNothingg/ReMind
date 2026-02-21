import React, { useRef, useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';

const Spinwheel = ({ initialState }) => {
    const { t } = useTranslation();
    const config = {
        min: initialState?.range?.min || 1,
        max: initialState?.range?.max || 100,
        step: initialState?.range?.step || 1,
        target: initialState?.number || 50,
        spinTime: initialState?.behavior?.spin_time_ms || 4200
    };

    const reelRef = useRef(null);
    const [isSpinning, setIsSpinning] = useState(false);
    const [hasSpun, setHasSpun] = useState(false);
    const segments = [];
    for (let i = config.min; i <= config.max; i += config.step) segments.push(i);
    const displaySegments = [...segments, ...segments, ...segments, ...segments, ...segments]; // ~ x5

    const itemHeight = 75; // Из CSS

    const spin = () => {
        if (isSpinning || hasSpun) return;
        setIsSpinning(true);
        setHasSpun(true);

        const targetIndex = segments.indexOf(Number(config.target));
        const middleOffset = segments.length * 2;
        const finalIndex = middleOffset + targetIndex;

        const finalPosition = finalIndex * itemHeight - (225 / 2) + (itemHeight / 2); // 225 - высота viewport
        const startPos = finalPosition - (segments.length * itemHeight * 2);

        if (reelRef.current) {
            reelRef.current.style.transition = 'none';
            reelRef.current.style.transform = `translateY(-${startPos}px)`;

            setTimeout(() => {
                reelRef.current.style.transition = `transform ${config.spinTime}ms cubic-bezier(0.25, 1, 0.5, 1)`;
                reelRef.current.style.transform = `translateY(-${finalPosition}px)`;
            }, 50);
        }

        setTimeout(() => {
            setIsSpinning(false);
        }, config.spinTime);
    };
    useEffect(() => {
        if(reelRef.current && !hasSpun) {
             const startIdx = segments.indexOf(config.min);
             const pos = (segments.length * 2 + startIdx) * itemHeight - (225/2) + (itemHeight/2);
             reelRef.current.style.transform = `translateY(-${pos}px)`;
        }
    }, []);

    return (
        <div className={`spin-wheel-container ${isSpinning ? 'spinning' : ''}`}>
            <div className="wheel-viewport">
                <ul className="wheel-reel" ref={reelRef}>
                    {displaySegments.map((num, i) => (
                        <li key={i} className={(!isSpinning && hasSpun && num === config.target) ? 'active' : ''}>
                            {num}
                        </li>
                    ))}
                </ul>
            </div>
            <div className="controls">
                {!hasSpun && (
                    <button className="spin-button" onClick={spin}>{t('spinwheel.spin')}</button>
                )}
            </div>
        </div>
    );
};

export default Spinwheel;
