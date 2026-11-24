import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

const LandingHero = ({
  children,
  isReadOnly = false,
  title = null,
}: {
  children: ReactNode;
  isReadOnly?: boolean;
  title?: string | null;
}) => {
  const { t } = useTranslation();

  return (
    <section className="landing-hero ui-landing-shell" aria-label={title || t('landing.ariaLabel')}>
      {isReadOnly && (
        <div className="readonly-banner ui-notice-banner ui-landing-readonly">
          <span>{t('landing.readonlyBanner')}</span>
        </div>
      )}

      <div className="ui-landing-center-stack">
        <div className="ui-landing-copy">
          <h1 className="ui-landing-greeting">{title || t('landing.greeting')}</h1>
        </div>

        {children}
      </div>
    </section>
  );
};

export default LandingHero;
