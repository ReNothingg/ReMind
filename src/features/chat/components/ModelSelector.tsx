import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';

import type { ThinkingLevel } from '../../../services/api';
import { cn } from '../../../utils/cn';
import { getModelStageLabel, type ChatModel } from '../modelSelection';

interface ModelOption {
    id: string;
    name: string;
    desc: string;
    badge?: string;
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
    const dropdownId = useId();
    const selectorRef = useRef<HTMLDivElement | null>(null);
    const { t } = useTranslation();

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as Node | null;
            if (selectorRef.current && target && !selectorRef.current.contains(target)) {
                setIsDropdownOpen(false);
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    useEffect(() => {
        if (!isDropdownOpen) return undefined;

        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return;
            event.preventDefault();
            setIsDropdownOpen(false);
            selectorRef.current?.querySelector<HTMLButtonElement>('.model-btn-trigger')?.focus();
        };

        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [isDropdownOpen]);

    const models: ModelOption[] = useMemo(() => availableModels.map((model) => {
        const badge = getModelStageLabel(model.stage);
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
            ...(badge ? { badge } : {}),
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
    const thinkingLevelIndex = Math.max(
        0,
        activeThinkingLevel ? supportedThinkingLevels.indexOf(activeThinkingLevel) : 0,
    );
    const thinkingThumbPosition = thinkingSliderPosition(
        thinkingLevelIndex,
        supportedThinkingLevels.length,
    );

    if (models.length === 0) {
        return null;
    }

    return (
        <div
            className={cn(
                'model-selector-new composer-model-selector',
                activeThinkingLevel && 'has-thinking-level',
            )}
            ref={selectorRef}
        >
            <button
                type="button"
                className={cn('model-btn-trigger', isDropdownOpen && 'open')}
                onClick={() => setIsDropdownOpen((open) => !open)}
                aria-expanded={isDropdownOpen}
                aria-haspopup="dialog"
                aria-controls={dropdownId}
            >
                <span className="model-btn-copy">
                    <span className="model-btn-name">{activeModel.name}</span>
                    {activeThinkingLevel && (
                        <span className="model-btn-variant" aria-live="polite">
                            {t(`models.thinkingLevels.${activeThinkingLevel}`)}
                        </span>
                    )}
                </span>
                <svg
                    className={cn('model-btn-chevron', isDropdownOpen && 'rotate-180')}
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
                className={cn(
                    'model-dropdown ui-toolbar-dropdown',
                    isDropdownOpen
                        ? 'open ui-toolbar-dropdown-open'
                        : 'ui-toolbar-dropdown-closed',
                )}
                role="dialog"
                aria-label={t('models.choose')}
            >
                <div className="model-options ui-toolbar-option-list">
                    {models.map((model) => {
                        const isSelected = currentModel === model.id;
                        return (
                            <div
                                key={model.id}
                                className={cn('model-option-card', isSelected && 'is-selected')}
                            >
                                <button
                                    type="button"
                                    className="model-option ui-toolbar-option"
                                    aria-pressed={isSelected}
                                    onClick={() => {
                                        onModelChange(model.id);
                                        if (!isSelected || model.thinkingLevels.length === 0) {
                                            setIsDropdownOpen(false);
                                        }
                                    }}
                                >
                                    <span className="model-option-header ui-toolbar-option-header">
                                        <span className="model-option-name ui-toolbar-option-name">
                                            {model.name}
                                        </span>
                                        {model.badge && (
                                            <span className="model-option-badge ui-toolbar-option-badge">
                                                {model.badge}
                                            </span>
                                        )}
                                    </span>
                                    {model.desc && (
                                        <span className="model-option-desc ui-toolbar-option-description">
                                            {model.desc}
                                        </span>
                                    )}
                                </button>

                                {isSelected && supportedThinkingLevels.length > 0 && activeThinkingLevel && (
                                    <section
                                        className="model-thinking-control"
                                        aria-label={t('models.thinkingLevel')}
                                    >
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
                                    </section>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}

export default ModelSelector;
