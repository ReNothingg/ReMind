import { useEffect, useId, useRef, useState } from 'react';
import type {
    ButtonHTMLAttributes,
    CSSProperties,
    ReactNode,
    RefObject,
} from 'react';
import { useTranslation } from 'react-i18next';
import { LockKeyhole } from 'lucide-react';
import type { ShareInfo } from '../../share/components/ShareModal';
import GuestButtons from './GuestButtons';
import { cn } from '../../../utils/cn';
import { getModelStageLabel, type ChatModel } from '../modelSelection';
import type { ThinkingLevel } from '../../../services/api';

interface GlobalHeaderProps {
    isAuthenticated: boolean;
    onMenuToggle: () => void;
    currentModel: string;
    models: ChatModel[];
    onModelChange: (modelId: string) => void;
    thinkingLevel: ThinkingLevel;
    onThinkingLevelChange: (level: ThinkingLevel) => void;
    onOpenAuth: () => void;
    onShowRegister: () => void;
    shareInfo?: ShareInfo | null;
    currentSessionId: string | null;
    isReadOnly: boolean;
    onOpenShareModal?: () => void;
    onNewChat: () => void;
    onTemporaryChat: () => void;
    isTemporaryChat?: boolean;
    showChatControls?: boolean;
    showTemporaryChatButton?: boolean;
}

interface ModelOption {
    id: string;
    name: string;
    desc: string;
    badge?: string;
    thinkingLevels: ThinkingLevel[];
    defaultThinkingLevel?: ThinkingLevel;
}

interface HeaderIconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    children: ReactNode;
}

interface ModelSelectorProps {
    activeModel: ModelOption;
    currentModel: string;
    dropdownId: string;
    dropdownRef: RefObject<HTMLDivElement | null>;
    isDropdownOpen: boolean;
    models: ModelOption[];
    onCloseDropdown: () => void;
    onModelChange: (modelId: string) => void;
    thinkingLevel: ThinkingLevel;
    onThinkingLevelChange: (level: ThinkingLevel) => void;
    onToggleDropdown: () => void;
    chooseLabel: string;
}

const THINKING_THUMB_RADIUS = 22;

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

function HeaderIconButton({
    children,
    className,
    type = 'button',
    ...props
}: HeaderIconButtonProps) {
    return (
        <button
            type={type}
            className={cn('ui-icon-control ui-toolbar-icon-button', className)}
            {...props}
        >
            {children}
        </button>
    );
}

export function ModelSelector({
    activeModel,
    currentModel,
    dropdownId,
    dropdownRef,
    isDropdownOpen,
    models,
    onCloseDropdown,
    onModelChange,
    thinkingLevel,
    onThinkingLevelChange,
    onToggleDropdown,
    chooseLabel,
}: ModelSelectorProps) {
    const { t } = useTranslation();
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

    return (
        <div
            className="model-selector-new ui-toolbar-anchor"
            ref={dropdownRef}
        >
            <button
                type="button"
                className={cn(
                    'model-btn-trigger ui-toolbar-trigger',
                    isDropdownOpen && 'open ui-toolbar-trigger-active'
                )}
                onClick={onToggleDropdown}
                aria-expanded={isDropdownOpen}
                aria-haspopup="dialog"
                aria-controls={dropdownId}
            >
                <span className="model-btn-copy">
                    <span className="model-btn-name ui-toolbar-trigger-label">
                        {activeModel.name}
                    </span>
                    {activeThinkingLevel && (
                        <span className="model-btn-variant" aria-live="polite">
                            {t(`models.thinkingLevels.${activeThinkingLevel}`)}
                        </span>
                    )}
                </span>
                <svg
                    className={cn(
                        'model-btn-chevron ui-toolbar-chevron',
                        isDropdownOpen && 'rotate-180'
                    )}
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    aria-hidden="true"
                >
                    <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
            </button>

            <div
                id={dropdownId}
                className={cn(
                    'model-dropdown ui-toolbar-dropdown',
                    isDropdownOpen
                        ? 'open ui-toolbar-dropdown-open'
                        : 'ui-toolbar-dropdown-closed'
                )}
                role="dialog"
                aria-label={chooseLabel}
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
                                            onCloseDropdown();
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

export default function GlobalHeader({
    isAuthenticated,
    onMenuToggle,
    currentModel,
    models: availableChatModels,
    onModelChange,
    thinkingLevel,
    onThinkingLevelChange,
    onOpenAuth,
    onShowRegister,
    shareInfo,
    currentSessionId,
    isReadOnly,
    onOpenShareModal,
    onNewChat,
    onTemporaryChat,
    isTemporaryChat = false,
    showChatControls = true,
    showTemporaryChatButton = true,
}: GlobalHeaderProps) {
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
    const modelDropdownId = useId();
    const dropdownRef = useRef<HTMLDivElement | null>(null);
    const { t } = useTranslation();

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as Node | null;
            if (dropdownRef.current && target && !dropdownRef.current.contains(target)) {
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
            dropdownRef.current?.querySelector<HTMLButtonElement>('.ui-toolbar-trigger')?.focus();
        };

        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [isDropdownOpen]);

    const models: ModelOption[] = availableChatModels.map((model) => {
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
    });

    const activeModel = models.find((model) => model.id === currentModel) ?? models[0] ?? {
        id: currentModel,
        name: currentModel,
        desc: '',
        thinkingLevels: [],
    };
    const isShared = !!shareInfo?.isPublic;
    const hasSession = !!currentSessionId;
    const shareButtonTitle = !hasSession
        ? t('share.enableFirst')
        : !isAuthenticated
          ? t('share.signinToManage')
          : isShared
            ? t('share.configure')
            : t('share.shareChat');

    return (
        <div className="global-controls ui-toolbar-shell">
            <div className="ui-toolbar-group">
                {!isAuthenticated && (
                    <GuestButtons
                        className="pointer-events-auto"
                        onOpenAuth={onOpenAuth}
                        onShowRegister={onShowRegister}
                    />
                )}

                {isAuthenticated && (
                    <HeaderIconButton
                        id="mobileMenuToggle"
                        className="mobile-menu-btn inline-flex md:hidden"
                        onClick={onMenuToggle}
                        title={t('app.menu')}
                        aria-label={t('app.menu')}
                    >
                        <svg className="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                            <line x1="3" y1="12" x2="21" y2="12"></line>
                            <line x1="3" y1="6" x2="21" y2="6"></line>
                            <line x1="3" y1="18" x2="21" y2="18"></line>
                        </svg>
                    </HeaderIconButton>
                )}

                {showChatControls && models.length > 0 && (
                    <ModelSelector
                        activeModel={activeModel}
                        currentModel={currentModel}
                        dropdownId={modelDropdownId}
                        dropdownRef={dropdownRef}
                        isDropdownOpen={isDropdownOpen}
                        models={models}
                        onCloseDropdown={() => setIsDropdownOpen(false)}
                        onModelChange={onModelChange}
                        thinkingLevel={thinkingLevel}
                        onThinkingLevelChange={onThinkingLevelChange}
                        onToggleDropdown={() => setIsDropdownOpen((prev) => !prev)}
                        chooseLabel={t('models.choose')}
                    />
                )}
            </div>

            <div className="ui-toolbar-actions">
                {showChatControls && !!currentSessionId && (
                    <div className="share-controls ui-toolbar-share-cluster">
                        <HeaderIconButton
                            className={cn(
                                'icon-btn share-icon',
                                isShared && 'active border-[rgba(var(--color-accent-raw),0.45)] bg-interactive'
                            )}
                            onClick={() => {
                                if (!hasSession) {
                                    return;
                                }

                                if (!isAuthenticated) {
                                    onOpenAuth();
                                    return;
                                }
                                onOpenShareModal?.();
                            }}
                            title={shareButtonTitle}
                            aria-label={t('share.shareChat')}
                            disabled={!hasSession}
                        >
                            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2">
                                <circle cx="6" cy="12" r="3"></circle>
                                <circle cx="18" cy="6" r="3"></circle>
                                <circle cx="18" cy="18" r="3"></circle>
                                <line x1="8.7" y1="10.7" x2="15.3" y2="7.3"></line>
                                <line x1="8.7" y1="13.3" x2="15.3" y2="16.7"></line>
                            </svg>
                        </HeaderIconButton>
                        {(isReadOnly || isShared) && (
                            <span
                                className="readonly-pill ui-toolbar-status-pill"
                                title={isReadOnly ? t('share.readOnly') : t('share.publicChat')}
                            >
                                {isReadOnly ? t('chat.readOnly') : t('share.publicChat')}
                            </span>
                        )}
                    </div>
                )}

                {showChatControls && isAuthenticated && (
                    <HeaderIconButton
                        className="new-chat-btn hidden text-foreground md:inline-flex"
                        onClick={onNewChat}
                        title={t('rail.newChat')}
                        aria-label={t('rail.newChat')}
                    >
                        <svg className="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M12 5v14M5 12h14"></path>
                        </svg>
                    </HeaderIconButton>
                )}

                {showChatControls && showTemporaryChatButton && (
                    <HeaderIconButton
                        className="ui-toolbar-temporary-button"
                        onClick={onTemporaryChat}
                        title={t('rail.temporaryChat')}
                        aria-label={t('rail.temporaryChat')}
                        aria-pressed={isTemporaryChat}
                    >
                        <LockKeyhole className="size-5" aria-hidden="true" />
                    </HeaderIconButton>
                )}
            </div>
        </div>
    );
}
