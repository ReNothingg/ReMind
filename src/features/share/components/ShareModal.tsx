import { useTranslation } from 'react-i18next';

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

    return (
        <div className="share-modal-overlay" onClick={onClose}>
            <div className="share-modal" onClick={(event) => event.stopPropagation()}>
                <div className="share-modal-header">
                    <div className="share-modal-title">{t('share.title')}</div>
                    <button className="share-modal-close" onClick={onClose} aria-label={t('share.close')}>
                        ✕
                    </button>
                </div>

                <div className="share-modal-body">
                    {!isAuthenticated && <div className="share-alert">{t('share.signinToManage')}</div>}

                    <div className="share-row">
                        <div className="share-label">{t('share.status')}</div>
                        <div className="share-status">
                            <span className={`share-badge ${isShared ? 'shared' : 'private'}`}>
                                {isShared ? t('share.public') : t('share.private')}
                            </span>
                        </div>
                        <button
                            className="share-toggle-btn"
                            onClick={isShared ? onDisableShare : onEnableShare}
                            disabled={!isAuthenticated}
                        >
                            {isShared ? t('share.disable') : t('share.enable')}
                        </button>
                    </div>

                    <div className="share-row">
                        <div className="share-label">{t('share.publicLink')}</div>
                        <div className="share-link">
                            <input type="text" value={isShared ? shareUrl : t('share.enableFirst')} readOnly />
                            <button
                                className="share-copy-icon"
                                onClick={async () => {
                                    if (!isShared || !shareUrl) {
                                        return;
                                    }
                                    try {
                                        await navigator.clipboard.writeText(shareUrl);
                                    } catch (error) {
                                        console.warn('Copy failed', error);
                                    }
                                }}
                                disabled={!isShared || !shareUrl}
                                title={t('share.copyLink')}
                                aria-label={t('share.copyLink')}
                            >
                                <img src="/icons/ui/copy.svg" alt="copy" />
                            </button>
                        </div>
                    </div>

                    <div className="share-tip">{t('share.tip')}</div>
                </div>
            </div>
        </div>
    );
}
