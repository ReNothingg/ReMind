import i18n, { type BackendModule, type ReadCallback } from 'i18next';
import { initReactI18next } from 'react-i18next';

const SUPPORTED_LANGUAGES = ['ru', 'en', 'zh', 'es', 'ar', 'hi', 'fr', 'bn', 'pt'];
export const DEFAULT_LANGUAGE = 'en';
export const LANGUAGE_STORAGE_KEY = 'remind:language';

const localeModules = import.meta.glob<{ default: unknown }>('./locales/*/*.json');

export function normalizeLanguage(language) {
  const value = String(language || '').toLowerCase();
  const match = SUPPORTED_LANGUAGES.find((lng) => value === lng || value.startsWith(`${lng}-`));
  return match || DEFAULT_LANGUAGE;
}

function detectInitialLanguage() {
  const saved = localStorage.getItem(LANGUAGE_STORAGE_KEY);
  if (saved) return normalizeLanguage(saved);
  return normalizeLanguage(navigator.language);
}

const lazyBackend: BackendModule = {
  type: 'backend',
  init: () => undefined,
  read(language: string, namespace: string, callback: ReadCallback) {
    const lng = normalizeLanguage(language);
    const key = `./locales/${lng}/${namespace}.json`;
    const loader = localeModules[key];

    if (!loader) {
      callback(new Error(`Missing locale module: ${key}`), false);
      return;
    }

    loader()
      .then((mod) => callback(null, mod.default))
      .catch((err) => callback(err, false));
  },
};

let initPromise;

export function initI18n() {
  if (initPromise) return initPromise;

  const initialLanguage = detectInitialLanguage();

  initPromise = i18n
    .use(lazyBackend)
    .use(initReactI18next)
    .init({
      lng: initialLanguage,
      supportedLngs: SUPPORTED_LANGUAGES,
      fallbackLng: DEFAULT_LANGUAGE,
      ns: ['common'],
      defaultNS: 'common',
      fallbackNS: 'common',
      load: 'languageOnly',
      interpolation: {
        escapeValue: false,
      },
      react: {
        useSuspense: false,
      },
    })
    .catch((err) => {
      console.warn('[i18n] init failed, continuing without translations:', err);
    });

  i18n.on('languageChanged', (lng) => {
    try {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, normalizeLanguage(lng));
    } catch {
    }
  });

  return initPromise;
}
