import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { LockKeyhole } from 'lucide-react';
import type { ShareInfo } from '../../share/components/ShareModal';
import GuestButtons from './GuestButtons';
import { cn } from '../../../utils/cn';

interface GlobalHeaderProps {
    isAuthenticated: boolean;
    onMenuToggle: () => void;
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

interface HeaderIconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    children: ReactNode;
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

export default function GlobalHeader({
    isAuthenticated,
    onMenuToggle,
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
    const { t } = useTranslation();
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
            <div
                className={cn(
                    'ui-toolbar-group ui-toolbar-navigation-group',
                    isAuthenticated && 'is-authenticated',
                )}
            >
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
