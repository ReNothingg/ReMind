import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import ModalShell from '../../../components/UI/ModalShell';
import { cn } from '../../../utils/cn';

export interface ShareInfo {
    isPublic?: boolean;
    publicId?: string | null;
    shareUrl?: string | null;
}

interface ShareModalProps {
    isOpen: boolean;
    onClose: () => void;
    shareInfo?: ShareInfo | null;
    onEnableShare: () => Promise<unknown> | unknown;
    onDisableShare: () => Promise<unknown> | unknown;
    isAuthenticated: boolean;
}

interface ShareRowProps {
    label: string;
    children: ReactNode;
}

function ShareRow({ label, children }: ShareRowProps) {
    return (
        <div className="share-row ui-share-row">
            <div className="share-label ui-share-label">{label}</div>
            {children}
        </div>
    );
}

export default function ShareModal({
    isOpen,
    onClose,
    shareInfo,
    onEnableShare,
    onDisableShare,
    isAuthenticated,
}: ShareModalProps) {
    const { t } = useTranslation();

    if (!isOpen) {
        return null;
    }

    const isShared = !!shareInfo?.isPublic;
    const shareUrl =
        shareInfo?.shareUrl ||
        (shareInfo?.publicId ? `${window.location.origin}/c/${shareInfo.publicId}` : '');
    const shareStatusLabel = isShared ? t('share.public') : t('share.private');

    const handleCopyLink = async () => {
        if (!isShared || !shareUrl) {
            return;
        }

        try {
            await navigator.clipboard.writeText(shareUrl);
        } catch (error) {
            console.warn('Copy failed', error);
        }
    };

    return (
        <ModalShell
            className="share-modal-overlay"
            contentClassName="share-modal ui-share-modal-card"
            onBackdropClick={onClose}
        >
            <div className="share-modal-header ui-share-modal-header">
                <div className="share-modal-title ui-share-modal-title">{t('share.title')}</div>
                <button
                    type="button"
                    className="share-modal-close ui-icon-control ui-share-modal-close ui-icon-dismiss"
                    onClick={onClose}
                    aria-label={t('share.close')}
                />
            </div>

            <div className="share-modal-body ui-share-modal-body">
                {!isAuthenticated && (
                    <div className="share-alert ui-share-alert">
                        {t('share.signinToManage')}
                    </div>
                )}

                <ShareRow label={t('share.status')}>
                    <div className="share-status ui-share-status">
                        <span className={cn('share-badge ui-badge', isShared ? 'shared' : 'private')}>
                            {shareStatusLabel}
                        </span>
                    </div>
                    <button
                        type="button"
                        className="share-toggle-btn ui-button-secondary px-3 py-2 text-sm"
                        onClick={isShared ? onDisableShare : onEnableShare}
                        disabled={!isAuthenticated}
                    >
                        {isShared ? t('share.disable') : t('share.enable')}
                    </button>
                </ShareRow>

                <ShareRow label={t('share.publicLink')}>
                    <div className="share-link ui-share-link">
                        <input
                            className="ui-input ui-share-input"
                            type="text"
                            value={isShared ? shareUrl : t('share.enableFirst')}
                            readOnly
                        />
                        <button
                            type="button"
                            className="share-copy-icon ui-icon-control ui-share-copy-button"
                            onClick={handleCopyLink}
                            disabled={!isShared || !shareUrl}
                            title={t('share.copyLink')}
                            aria-label={t('share.copyLink')}
                        >
                            <img src="/icons/ui/copy.svg" alt="copy" className="h-[18px] w-[18px]" />
                        </button>
                    </div>
                </ShareRow>

                <div className="share-tip ui-share-tip">{t('share.tip')}</div>
            </div>
        </ModalShell>
    );
}
