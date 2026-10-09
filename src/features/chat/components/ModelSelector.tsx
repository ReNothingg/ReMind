import { useEffect, useLayoutEffect, useId, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';

import type { ThinkingLevel } from '../../../services/api';
import { cn } from '../../../utils/cn';
import { isImageToolModel, type ChatModel } from '../modelSelection';

interface ModelOption {
    id: string;
    name: string;
    desc: string;
    thinkingLevels: ThinkingLevel[];
    defaultThinkingLevel?: ThinkingLevel;
}

interface ModelSelectorProps {
    currentModel: string;
    models: ChatModel[];
    onModelChange: (modelId: string) => void;
    thinkingLevel: ThinkingLevel;
    onThinkingLevelChange: (level: ThinkingLevel) => void;
}

const THINKING_THUMB_RADIUS = 18;

function thinkingSliderPosition(index: number, count: number): string {
    if (count <= 1 || index <= 0) {
        return `${THINKING_THUMB_RADIUS}px`;
    }
    if (index >= count - 1) {
        return `calc(100% - ${THINKING_THUMB_RADIUS}px)`;
    }
    const ratio = index / (count - 1);
    const percentage = ratio * 100;
    const pixelCorrection = THINKING_THUMB_RADIUS - (THINKING_THUMB_RADIUS * 2 * ratio);
    const operator = pixelCorrection >= 0 ? '+' : '-';
    return `calc(${percentage}% ${operator} ${Math.abs(pixelCorrection)}px)`;
}

export function ModelSelector({
    currentModel,
    models: availableModels,
    onModelChange,
    thinkingLevel,
    onThinkingLevelChange,
}: ModelSelectorProps) {
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
    const [view, setView] = useState<'thinking' | 'models'>('thinking');
    const dropdownId = useId();
    const dropdownRef = useRef<HTMLDivElement | null>(null);
    const panelHeightRef = useRef<number | null>(null);
    const selectorRef = useRef<HTMLDivElement | null>(null);
    const { t } = useTranslation();

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as Node | null;
            if (selectorRef.current && target && !selectorRef.current.contains(target)) {
                setIsDropdownOpen(false);
            }
        };

        document.addEventListener('pointerdown', handleClickOutside);
        return () => document.removeEventListener('pointerdown', handleClickOutside);
    }, []);

    useEffect(() => {
        if (!isDropdownOpen) return undefined;

        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return;
            event.preventDefault();
            if (view === 'models') {
                setView('thinking');
            } else {
                setIsDropdownOpen(false);
                selectorRef.current?.querySelector<HTMLButtonElement>('.model-btn-trigger')?.focus();
            }
        };

        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [isDropdownOpen, view]);

    useLayoutEffect(() => {
        if (!isDropdownOpen) return;


        selectorRef.current?.querySelector<HTMLButtonElement>(
            view === 'models' ? '.model-option[aria-pressed="true"]' : '.model-panel-heading',
        )?.focus({ preventScroll: true });
    }, [isDropdownOpen, view]);

    const models: ModelOption[] = useMemo(() => availableModels.filter((model) => !isImageToolModel(model)).map((model) => {
        return {
            id: model.id,
            name: model.titleKey ? t(model.titleKey, { defaultValue: model.title }) : model.title,
            desc: model.subtitleKey
                ? t(model.subtitleKey, { defaultValue: model.subtitle })
                : model.subtitle,
            thinkingLevels: model.thinkingLevels,
            ...(model.defaultThinkingLevel
                ? { defaultThinkingLevel: model.defaultThinkingLevel }
                : {}),
        };
    }), [availableModels, t]);

    const activeModel = models.find((model) => model.id === currentModel) ?? models[0] ?? {
        id: currentModel,
        name: currentModel,
        desc: '',
        thinkingLevels: [],
    };
    const supportedThinkingLevels = activeModel.thinkingLevels || [];
    const activeThinkingLevel = supportedThinkingLevels.includes(thinkingLevel)
        ? thinkingLevel
        : activeModel.defaultThinkingLevel || supportedThinkingLevels[0];
    const thinkingLabel = supportedThinkingLevels.length === 2
        ? t('models.think')
        : activeThinkingLevel ? t(`models.thinkingLevels.${activeThinkingLevel}`) : '';
    const thinkingLevelIndex = Math.max(
        0,
        activeThinkingLevel ? supportedThinkingLevels.indexOf(activeThinkingLevel) : 0,
    );
    const thinkingThumbPosition = thinkingSliderPosition(
        thinkingLevelIndex,
        supportedThinkingLevels.length,
    );

    useLayoutEffect(() => {
        const dropdown = dropdownRef.current;
        if (!dropdown || !isDropdownOpen) return;
        const previousHeight = panelHeightRef.current;
        dropdown.style.height = 'auto';
        const nextHeight = dropdown.offsetHeight;
        panelHeightRef.current = nextHeight;
        if (previousHeight === null || previousHeight === nextHeight
            || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
        const animation = dropdown.animate(
            [{ height: `${previousHeight}px` }, { height: `${nextHeight}px` }],
            { duration: 240, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' },
        );
        return () => animation.cancel();
    }, [isDropdownOpen, view, activeModel.name, thinkingLabel, models]);

    if (models.length === 0) {
        return null;
    }

    return (
        <div
            className={cn(
                'model-selector-new composer-model-selector compact-model-selector',
                activeThinkingLevel && 'has-thinking-level',
            )}
            ref={selectorRef}
        >
            <button
                type="button"
                className={cn('model-btn-trigger', isDropdownOpen && 'open')}
                onClick={() => {
                    setView('thinking');
                    setIsDropdownOpen((open) => !open);
                }}
                aria-expanded={isDropdownOpen}
                aria-haspopup="dialog"
                aria-controls={dropdownId}
            >
                <span className="model-btn-copy">
                    <span className="model-btn-name">{activeModel.name}</span>
                    {activeThinkingLevel && (supportedThinkingLevels.length !== 2 || thinkingLevelIndex === 1) && (
                        <span className="model-effort-indicator" role="img"
                            aria-label={`${t('models.thinkingLevel')}: ${thinkingLabel}`}
                            title={`${t('models.thinkingLevel')}: ${thinkingLabel}`}>
                            <svg className="model-effort-dial" viewBox="0 0 20 20" aria-hidden="true">
                                <circle className="model-effort-orbit" cx="10" cy="10" r="7" />
                                <circle className="model-effort-ring" cx="10" cy="10" r="7" pathLength="100"
                                    strokeDasharray="100"
                                    strokeDashoffset={100 - (thinkingLevelIndex + 1) / supportedThinkingLevels.length * 100} />
                                <circle className="model-effort-core" cx="10" cy="10" r="1.5"
                                    style={{ opacity: 0.35 + (thinkingLevelIndex + 1) / supportedThinkingLevels.length * 0.65 }} />
                            </svg>
                        </span>
                    )}
                </span>
                <svg
                    className="model-btn-chevron"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    aria-hidden="true"
                >
                    <polyline points="6 9 12 15 18 9" />
                </svg>
            </button>

            <div
                id={dropdownId}
                ref={dropdownRef}
                className={cn(
                    'model-dropdown ui-toolbar-dropdown',
                    isDropdownOpen
                        ? 'open ui-toolbar-dropdown-open'
                        : 'ui-toolbar-dropdown-closed',
                )}
                inert={!isDropdownOpen}
                role="dialog"
                aria-label={t(view === 'models' ? 'models.choose' : 'models.thinkingLevel')}
            >
                {view === 'thinking' ? (
                    <div key="thinking" className="model-thinking-panel model-panel-enter-back">
                        <button type="button" className="model-panel-heading"
                            onClick={() => setView('models')}
                            aria-label={`${activeModel.name}: ${t('models.choose')}`}>
                            <span className="model-panel-name">{activeModel.name}</span>
                            {supportedThinkingLevels.length > 2 && (
                                <span className="model-effort-value" aria-live="polite">{thinkingLabel}</span>
                            )}
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                                <path d="m9 5 7 7-7 7" />
                            </svg>
                        </button>
                        {supportedThinkingLevels.length > 0 && activeThinkingLevel && (
                            <section
                                className="model-thinking-control"
                                aria-label={t('models.thinkingLevel')}
                            >
                                {supportedThinkingLevels.length === 2 ? (
                                    <button type="button" className="model-thinking-toggle" role="switch"
                                        aria-checked={activeThinkingLevel === supportedThinkingLevels[1]}
                                        onClick={() => onThinkingLevelChange(supportedThinkingLevels[activeThinkingLevel === supportedThinkingLevels[1] ? 0 : 1]!)}>
                                        <span>{t('models.think')}</span><span className="model-thinking-switch" aria-hidden="true" />
                                    </button>
                                ) : (
                                    <div
                                        className="model-thinking-slider"
                                        style={{
                                            '--thinking-thumb-position': thinkingThumbPosition,
                                        } as CSSProperties}
                                    >
                                        <div className="model-thinking-track" aria-hidden="true">
                                            <span className="model-thinking-track-fill" />
                                            {supportedThinkingLevels.map((level, index) => (
                                                <span
                                                    key={level}
                                                    className={cn(
                                                        'model-thinking-marker',
                                                        index <= thinkingLevelIndex && 'is-active',
                                                    )}
                                                    style={{
                                                        left: thinkingSliderPosition(
                                                            index,
                                                            supportedThinkingLevels.length,
                                                        ),
                                                    }}
                                                />
                                            ))}
                                        </div>
                                        <input
                                            className="model-thinking-input"
                                            type="range"
                                            min="0"
                                            max={supportedThinkingLevels.length - 1}
                                            step="1"
                                            value={thinkingLevelIndex}
                                            onChange={(event) => {
                                                const nextLevel = supportedThinkingLevels[Number(event.target.value)];
                                                if (nextLevel) {
                                                    onThinkingLevelChange(nextLevel);
                                                }
                                            }}
                                            aria-label={t('models.thinkingLevel')}
                                            aria-valuetext={t(`models.thinkingLevels.${activeThinkingLevel}`)}
                                        />
                                    </div>
                                )}
                            </section>
                        )}
                    </div>
                ) : (
                    <div key="models" className="model-options ui-toolbar-option-list model-panel-enter-forward">
                        {models.map((model) => (
                            <button key={model.id} type="button" className="model-option ui-toolbar-option"
                                aria-pressed={activeModel.id === model.id}
                                onClick={() => {
                                    onModelChange(model.id);
                                    setView('thinking');
                                }}>
                                <span className="model-option-header">
                                    <span className="model-option-name">{model.name}</span>
                                    {activeModel.id === model.id && (
                                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                                            <path d="m5 12 4 4L19 5" />
                                        </svg>
                                    )}
                                </span>
                                {model.desc && <span className="model-option-desc">{model.desc}</span>}
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

export default ModelSelector;
