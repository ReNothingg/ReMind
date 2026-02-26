import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { ShareInfo } from '../../share/components/ShareModal';

interface GlobalHeaderProps {
    isAuthenticated: boolean;
    onMenuToggle: () => void;
    currentModel: string;
    onModelChange: (modelId: string) => void;
    onGuestModalOpen: () => void;
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

export default function GlobalHeader({
    isAuthenticated,
    onMenuToggle,
    currentModel,
    onModelChange,
    onGuestModalOpen,
    onOpenAuth,
    onShowRegister,
    shareInfo,
    currentSessionId,
    isReadOnly,
    onOpenShareModal,
    onNewChat,
}: GlobalHeaderProps) {
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
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
        <div className="global-controls">
            {!isAuthenticated && (
                <div className="guest-auth-buttons" id="guestAuthButtons">
                    <button
                        className="guest-btn guest-login-btn"
                        onClick={onOpenAuth}
                        aria-label={t('auth.login')}
                    >
                        {t('auth.login')}
                    </button>
                    <button
                        className="guest-btn guest-register-btn"
                        onClick={onShowRegister}
                        aria-label={t('auth.register')}
                    >
                        {t('auth.register')}
                    </button>
                </div>
            )}

            {isAuthenticated && (
                <button id="mobileMenuToggle" className="mobile-menu-btn" onClick={onMenuToggle} title={t('app.menu')}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="3" y1="12" x2="21" y2="12"></line>
                        <line x1="3" y1="6" x2="21" y2="6"></line>
                        <line x1="3" y1="18" x2="21" y2="18"></line>
                    </svg>
                </button>
            )}

            {isAuthenticated ? (
                <div className="model-selector-new" ref={dropdownRef}>
                    <button
                        className={`model-btn-trigger ${isDropdownOpen ? 'open' : ''}`}
                        onClick={(event) => {
                            if (!isAuthenticated) {
                                event.preventDefault();
                                event.stopPropagation();
                                onGuestModalOpen();
                                return;
                            }
                            setIsDropdownOpen((prev) => !prev);
                        }}
                    >
                        <span className="model-btn-icon"></span>
                        <span className="model-btn-name">{activeModel.name}</span>
                        <svg className="model-btn-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                    </button>

                    <div className={`model-dropdown ${isDropdownOpen ? 'open' : ''}`}>
                        <div className="model-dropdown-header">
                            <span className="model-dropdown-title">{t('models.choose')}</span>
                            <button className="model-dropdown-close" onClick={() => setIsDropdownOpen(false)}>
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <line x1="18" y1="6" x2="6" y2="18"></line>
                                    <line x1="6" y1="6" x2="18" y2="18"></line>
                                </svg>
                            </button>
                        </div>
                        <div className="model-options">
                            {models.map((model) => (
                                <div
                                    key={model.id}
                                    className="model-option"
                                    aria-selected={currentModel === model.id}
                                    onClick={(event) => {
                                        if (!isAuthenticated) {
                                            event.preventDefault();
                                            event.stopPropagation();
                                            setIsDropdownOpen(false);
                                            onShowRegister();
                                            return;
                                        }
                                        onModelChange(model.id);
                                        setIsDropdownOpen(false);
                                    }}
                                >
                                    <div className="model-option-header">
                                        <span className="model-option-name">{model.name}</span>
                                        {model.badge && <span className="model-option-badge">{model.badge}</span>}
                                    </div>
                                    <span className="model-option-desc">{model.desc}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            ) : (
                <div className="model-selector-new" ref={dropdownRef}>
                    <button
                        className="model-btn-trigger"
                        onClick={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            onOpenAuth();
                        }}
                    >
                        <span className="model-btn-icon"></span>
                        <span className="model-btn-name">Gemini</span>
                        <svg className="model-btn-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                    </button>
                </div>
            )}

            {!!currentSessionId && (
                <div className="share-controls">
                    <button
                        className={`icon-btn share-icon ${isShared ? 'active' : ''}`}
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
                    </button>
                    {(isReadOnly || isShared) && (
                        <span className="readonly-pill" title={isReadOnly ? t('share.readOnly') : t('share.publicChat')}>
                            {isReadOnly ? t('chat.readOnly') : t('share.publicChat')}
                        </span>
                    )}
                </div>
            )}

            {isAuthenticated && (
                <button className="new-chat-btn" onClick={onNewChat} title={t('rail.newChat')} aria-label={t('rail.newChat')}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 5v14M5 12h14"></path>
                    </svg>
                </button>
            )}
        </div>
    );
}
