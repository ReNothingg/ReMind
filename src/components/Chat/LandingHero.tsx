import React from 'react';
import { useTranslation } from 'react-i18next';

const LandingHero = ({ children, isReadOnly = false }) => {
    const { t } = useTranslation();

    return (
        <section className="landing-hero ui-landing-shell" aria-label={t('landing.ariaLabel')}>
            {isReadOnly && (
                <div className="readonly-banner ui-notice-banner ui-landing-readonly">
                    <span>{t('landing.readonlyBanner')}</span>
                </div>
            )}

            {children}
        </section>
    );
};

export default LandingHero;
