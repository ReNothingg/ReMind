import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../context/AuthContext';
import ModalShell from '../UI/ModalShell';
import GuestButtons from '../../features/chat/components/GuestButtons';

const guestModalPrimaryButtonClass =
    'ui-button-primary ui-guest-button-primary w-full rounded-xl px-5 py-3 text-[0.95rem] font-semibold';
const guestModalSecondaryButtonClass =
    'ui-button-secondary ui-guest-button-secondary w-full rounded-xl px-5 py-3 text-[0.95rem] font-semibold';

const guestFeatures = [
    {
        icon: '\uD83D\uDCA1',
        text: '\u0423\u043C\u043D\u044B\u0435 \u043E\u0442\u0432\u0435\u0442\u044B',
    },
    {
        icon: '\uD83D\uDCC1',
        text: '\u0417\u0430\u0433\u0440\u0443\u0437\u043A\u0430 \u0444\u0430\u0439\u043B\u043E\u0432',
    },
    {
        icon: '\uD83C\uDFA8',
        text: '\u0413\u0435\u043D\u0435\u0440\u0430\u0446\u0438\u044F \u0438\u0437\u043E\u0431\u0440\u0430\u0436\u0435\u043D\u0438\u0439',
    },
    {
        icon: '\u26A1',
        text: '\u0411\u044B\u0441\u0442\u0440\u043E \u0438 \u043F\u0440\u043E\u0441\u0442\u043E',
    },
];

const guestCopy = {
    modalTitleLineOne:
        '\u041F\u043E\u043F\u0440\u043E\u0431\u0443\u0439\u0442\u0435 \u0440\u0430\u0441\u0448\u0438\u0440\u0435\u043D\u043D\u044B\u0435',
    modalTitleLineTwo:
        '\u0444\u0443\u043D\u043A\u0446\u0438\u0438 \u0431\u0435\u0441\u043F\u043B\u0430\u0442\u043D\u043E',
    modalDescription:
        '\u041F\u043E\u043B\u0443\u0447\u0430\u0439\u0442\u0435 \u0431\u043E\u043B\u0435\u0435 \u0443\u043C\u043D\u044B\u0435 \u043E\u0442\u0432\u0435\u0442\u044B, \u0437\u0430\u0433\u0440\u0443\u0436\u0430\u0439\u0442\u0435 \u0444\u0430\u0439\u043B\u044B, \u0441\u043E\u0437\u0434\u0430\u0432\u0430\u0439\u0442\u0435 \u0438\u0437\u043E\u0431\u0440\u0430\u0436\u0435\u043D\u0438\u044F \u0438 \u043C\u043D\u043E\u0433\u043E\u0435 \u0434\u0440\u0443\u0433\u043E\u0435.',
    emptyTitle:
        '\u0414\u043E\u0431\u0440\u043E \u043F\u043E\u0436\u0430\u043B\u043E\u0432\u0430\u0442\u044C \u0432 ReMind',
    emptyDescription:
        '\u0412\u0430\u0448 \u043F\u0435\u0440\u0441\u043E\u043D\u0430\u043B\u044C\u043D\u044B\u0439 \u0430\u0441\u0441\u0438\u0441\u0442\u0435\u043D\u0442 \u0434\u043B\u044F \u043F\u0440\u043E\u0434\u0443\u043A\u0442\u0438\u0432\u043D\u043E\u0441\u0442\u0438, \u043E\u0431\u0443\u0447\u0435\u043D\u0438\u044F \u0438 \u0440\u0430\u0437\u0432\u0438\u0442\u0438\u044F.',
    emptyRegister:
        '\u0417\u0430\u0440\u0435\u0433\u0438\u0441\u0442\u0440\u0438\u0440\u043E\u0432\u0430\u0442\u044C\u0441\u044F \u0431\u0435\u0441\u043F\u043B\u0430\u0442\u043D\u043E',
    emptyLogin:
        '\u0423\u0436\u0435 \u0435\u0441\u0442\u044C \u0430\u043A\u043A\u0430\u0443\u043D\u0442? \u0412\u043E\u0439\u0442\u0438',
};

interface GuestModeManagerProps {
    children: ReactNode;
}

interface GuestModalProps {
    isOpen: boolean;
    onClose: () => void;
    onOpenAuth: () => void;
    onShowRegister: () => void;
}

interface GuestEmptyStateProps {
    onOpenAuth: () => void;
    onShowRegister: () => void;
}

export const GuestModeManager = ({ children }: GuestModeManagerProps) => {
    const { isAuthenticated } = useAuth();

    useEffect(() => {
        document.body.classList.toggle('guest-mode', !isAuthenticated);

        return () => {
            document.body.classList.remove('guest-mode');
        };
    }, [isAuthenticated]);

    return <>{children}</>;
};

export const GuestModal = ({ isOpen, onClose, onOpenAuth, onShowRegister }: GuestModalProps) => {
    const { t } = useTranslation();

    if (!isOpen) return null;

    return (
        <ModalShell
            className="bg-[rgba(var(--color-black-raw),0.72)] backdrop-blur-md"
            contentClassName="ui-guest-modal-card"
            onBackdropClick={onClose}
        >
            <div
                id="guestModal"
                className="ui-guest-modal-content"
                role="dialog"
                aria-modal="true"
                aria-labelledby="guestModalTitle"
            >
                <div className="ui-guest-modal-header">
                    <button
                        type="button"
                        className="ui-guest-modal-close ui-icon-dismiss"
                        id="guestModalClose"
                        onClick={onClose}
                        aria-label={t('translationPanel.close')}
                    />
                </div>
                <div className="ui-guest-modal-body">
                    <h2 id="guestModalTitle" className="ui-guest-modal-title">
                        {guestCopy.modalTitleLineOne}
                        <br />
                        {guestCopy.modalTitleLineTwo}
                    </h2>
                    <p className="ui-guest-modal-description">{guestCopy.modalDescription}</p>
                    <div className="ui-guest-modal-actions">
                        <button
                            type="button"
                            className={guestModalPrimaryButtonClass}
                            id="guestModalRegisterBtn"
                            onClick={() => {
                                onClose();
                                onShowRegister();
                            }}
                        >
                            {t('auth.register')}
                        </button>
                        <button
                            type="button"
                            className={guestModalSecondaryButtonClass}
                            id="guestModalLoginBtn"
                            onClick={() => {
                                onClose();
                                onOpenAuth();
                            }}
                        >
                            {t('auth.login')}
                        </button>
                    </div>
                </div>
            </div>
        </ModalShell>
    );
};

export const GuestEmptyState = ({ onOpenAuth, onShowRegister }: GuestEmptyStateProps) => {
    return (
        <div className="ui-guest-empty-shell">
            <h1 className="ui-guest-empty-title">{guestCopy.emptyTitle}</h1>
            <p className="ui-guest-empty-description">{guestCopy.emptyDescription}</p>
            <div className="ui-guest-feature-grid">
                {guestFeatures.map((feature) => (
                    <div key={feature.text} className="ui-guest-feature-card">
                        <div className="ui-guest-feature-icon">{feature.icon}</div>
                        <p className="ui-guest-feature-text">{feature.text}</p>
                    </div>
                ))}
            </div>
            <div className="ui-guest-cta-stack">
                <button
                    type="button"
                    className="ui-button-primary ui-guest-button-primary w-full rounded-xl px-6 py-3.5 text-[0.95rem] font-semibold"
                    id="guestEmptyRegisterBtn"
                    onClick={onShowRegister}
                >
                    {guestCopy.emptyRegister}
                </button>
                <button
                    type="button"
                    className="ui-button-secondary ui-guest-button-secondary w-full rounded-xl px-6 py-3.5 text-[0.95rem] font-semibold"
                    id="guestEmptyLoginBtn"
                    onClick={onOpenAuth}
                >
                    {guestCopy.emptyLogin}
                </button>
            </div>
        </div>
    );
};
