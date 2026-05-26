import { useTranslation } from 'react-i18next';
import { cn } from '../../../utils/cn';

interface GuestButtonsProps {
    className?: string;
    onOpenAuth?: () => void;
    onShowRegister?: () => void;
}

const guestSecondaryButtonClass = 'ui-button-secondary ui-guest-button-secondary';
const guestPrimaryButtonClass = 'ui-button-primary ui-guest-button-primary';

export default function GuestButtons({
    className,
    onOpenAuth,
    onShowRegister,
}: GuestButtonsProps) {
    const { t } = useTranslation();

    return (
        <div className={cn('ui-guest-inline-actions', className)} id="guestAuthButtons">
            <button
                type="button"
                className={guestSecondaryButtonClass}
                onClick={() => onOpenAuth?.()}
                aria-label={t('auth.login')}
            >
                {t('auth.login')}
            </button>
            <button
                type="button"
                className={guestPrimaryButtonClass}
                onClick={() => onShowRegister?.()}
                aria-label={t('auth.register')}
            >
                {t('auth.register')}
            </button>
        </div>
    );
}
