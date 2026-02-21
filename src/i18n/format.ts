import i18n, { DEFAULT_LANGUAGE } from './index';

const localeByLanguage = {
  en: 'en-US',
  ru: 'ru-RU',
  zh: 'zh-CN',
  es: 'es-ES',
  ar: 'ar',
  hi: 'hi-IN',
  fr: 'fr-FR',
  bn: 'bn-BD',
  pt: 'pt-PT',
};

export function getLocale(language) {
  const lng = String(language || i18n.resolvedLanguage || i18n.language || DEFAULT_LANGUAGE);
  const normalized = lng.toLowerCase();
  const match = Object.keys(localeByLanguage).find((key) => normalized === key || normalized.startsWith(`${key}-`));
  const fallback = DEFAULT_LANGUAGE.toLowerCase().startsWith('ru') ? 'ru' : 'en';
  const resolved = match || fallback;
  return localeByLanguage[resolved] || localeByLanguage.en;
}

export function formatNumber(value, options, language) {
  return new Intl.NumberFormat(getLocale(language), options).format(value);
}

export function formatDate(value, options, language) {
  const date = value instanceof Date ? value : new Date(value);
  return new Intl.DateTimeFormat(getLocale(language), options).format(date);
}

export function formatDateTime(value, options, language) {
  return formatDate(
    value,
    {
      dateStyle: 'medium',
      timeStyle: 'short',
      ...options,
    },
    language,
  );
}
