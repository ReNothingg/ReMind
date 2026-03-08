import { useEffect, useId, useRef, useState } from 'react';
import type { ButtonHTMLAttributes, ReactNode, RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import type { ShareInfo } from '../../share/components/ShareModal';
import GuestButtons from './GuestButtons';
import { cn } from '../../../utils/cn';

interface GlobalHeaderProps {
    isAuthenticated: boolean;
    onMenuToggle: () => void;
    currentModel: string;
    onModelChange: (modelId: string) => void;
    onOpenAuth: () => void;
    onShowRegister: () => void;
    shareInfo?: ShareInfo | null;
    currentSessionId: string | null;
    isReadOnly: boolean;
    onOpenShareModal?: () => void;
    onNewChat: () => void;
}

interface ModelOption {
    id: string;
    name: string;
    desc: string;
    badge?: string;
}

interface HeaderIconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    children: ReactNode;
}

interface ModelSelectorProps {
    activeModel: ModelOption;
    currentModel: string;
    dropdownId: string;
    dropdownRef: RefObject<HTMLDivElement | null>;
    isAuthenticated: boolean;
    isDropdownOpen: boolean;
    models: ModelOption[];
    onCloseDropdown: () => void;
    onModelChange: (modelId: string) => void;
    onOpenAuth: () => void;
    onToggleDropdown: () => void;
    chooseLabel: string;
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

function ModelSelector({
    activeModel,
    currentModel,
    dropdownId,
    dropdownRef,
    isAuthenticated,
    isDropdownOpen,
    models,
    onCloseDropdown,
    onModelChange,
    onOpenAuth,
    onToggleDropdown,
    chooseLabel,
}: ModelSelectorProps) {
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
                onClick={(event) => {
                    if (!isAuthenticated) {
                        event.preventDefault();
                        event.stopPropagation();
                        onOpenAuth();
                        return;
                    }

                    onToggleDropdown();
                }}
                aria-expanded={isAuthenticated ? isDropdownOpen : undefined}
                aria-haspopup={isAuthenticated ? 'listbox' : undefined}
                aria-controls={isAuthenticated ? dropdownId : undefined}
            >
                <span className="model-btn-name ui-toolbar-trigger-label">
                    {isAuthenticated ? activeModel.name : 'Gemini'}
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

            {isAuthenticated && (
                <div
                    id={dropdownId}
                    className={cn(
                        'model-dropdown ui-toolbar-dropdown',
                        isDropdownOpen
                            ? 'open ui-toolbar-dropdown-open'
                            : 'ui-toolbar-dropdown-closed'
                    )}
                    role="listbox"
                    aria-label={chooseLabel}
                >
                    <div className="model-dropdown-header ui-toolbar-dropdown-header">
                        <span className="model-dropdown-title ui-toolbar-dropdown-title">
                            {chooseLabel}
                        </span>
                    </div>
                    <div className="model-options ui-toolbar-option-list">
                        {models.map((model) => (
                            <button
                                key={model.id}
                                type="button"
                                className="model-option ui-toolbar-option"
                                aria-selected={currentModel === model.id}
                                role="option"
                                onClick={() => {
                                    onModelChange(model.id);
                                    onCloseDropdown();
                                }}
                            >
                                <div className="model-option-header ui-toolbar-option-header">
                                    <span className="model-option-name ui-toolbar-option-name">
                                        {model.name}
                                    </span>
                                    {model.badge && (
                                        <span className="model-option-badge ui-toolbar-option-badge">
                                            {model.badge}
                                        </span>
                                    )}
                                </div>
                                <span className="model-option-desc ui-toolbar-option-description">
                                    {model.desc}
                                </span>
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

export default function GlobalHeader({
    isAuthenticated,
    onMenuToggle,
    currentModel,
    onModelChange,
    onOpenAuth,
    onShowRegister,
    shareInfo,
    currentSessionId,
    isReadOnly,
    onOpenShareModal,
    onNewChat,
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

    const defaultModel: ModelOption = {
        id: 'gemini',
        name: 'Gemini',
        desc: t('models.gemini.desc'),
        badge: t('models.gemini.badge'),
    };
    const models: ModelOption[] = [
        defaultModel,
        { id: 'echo', name: 'Echo', desc: t('models.echo.desc') },
    ];

    const activeModel = models.find((model) => model.id === currentModel) ?? defaultModel;
    const isShared = !!shareInfo?.isPublic;
    const canShare = isAuthenticated && !!currentSessionId;

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

                <ModelSelector
                    activeModel={activeModel}
                    currentModel={currentModel}
                    dropdownId={modelDropdownId}
                    dropdownRef={dropdownRef}
                    isAuthenticated={isAuthenticated}
                    isDropdownOpen={isDropdownOpen}
                    models={models}
                    onCloseDropdown={() => setIsDropdownOpen(false)}
                    onModelChange={onModelChange}
                    onOpenAuth={onOpenAuth}
                    onToggleDropdown={() => setIsDropdownOpen((prev) => !prev)}
                    chooseLabel={t('models.choose')}
                />
            </div>

            <div className="ui-toolbar-actions">
                {!!currentSessionId && (
                    <div className="share-controls ui-toolbar-share-cluster">
                        <HeaderIconButton
                            className={cn(
                                'icon-btn share-icon',
                                isShared && 'active border-[rgba(var(--color-accent-raw),0.45)] bg-interactive'
                            )}
                            onClick={() => {
                                if (!canShare) {
                                    onOpenAuth();
                                    return;
                                }
                                onOpenShareModal?.();
                            }}
                            title={isShared ? t('share.configure') : t('share.shareChat')}
                            aria-label={t('share.shareChat')}
                            disabled={!canShare}
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

                {isAuthenticated && (
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
            </div>
        </div>
    );
}
