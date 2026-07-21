import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const localeDir = path.resolve(process.cwd(), 'src/i18n/locales');
const locales = ['ar', 'bn', 'en', 'es', 'fr', 'hi', 'pt', 'ru', 'zh'] as const;
const qualityPassLocales = ['ar', 'bn', 'es', 'fr', 'hi', 'pt', 'zh'] as const;

const requiredTextPaths = [
  ['authModal', 'fields', 'name'],
  ['settings', 'account', 'fields', 'name'],
  ['settings', 'account', 'nameHint'],
  ['settings', 'account', 'usernameHint'],
  ['settings', 'account', 'delete', 'title'],
  ['settings', 'account', 'delete', 'description'],
  ['settings', 'account', 'delete', 'confirmLabel'],
  ['settings', 'account', 'delete', 'confirmHint'],
  ['settings', 'account', 'delete', 'confirmPlaceholder'],
  ['settings', 'account', 'delete', 'confirmationMismatch'],
  ['settings', 'account', 'delete', 'action'],
  ['settings', 'account', 'delete', 'actionLoading'],
  ['settings', 'account', 'delete', 'success'],
  ['settings', 'account', 'delete', 'error'],
  ['settings', 'account', 'connectedApps', 'title'],
  ['settings', 'account', 'connectedApps', 'description'],
  ['settings', 'account', 'connectedApps', 'github', 'name'],
  ['settings', 'account', 'connectedApps', 'github', 'description'],
  ['settings', 'account', 'connectedApps', 'github', 'connect'],
  ['settings', 'account', 'connectedApps', 'github', 'manage'],
  ['settings', 'account', 'connectedApps', 'github', 'error'],
  ['settings', 'account', 'connectedApps', 'github', 'repoCount'],
  ['settings', 'account', 'connectedApps', 'github', 'status', 'checking'],
  ['settings', 'account', 'connectedApps', 'github', 'status', 'connected'],
  ['settings', 'account', 'connectedApps', 'github', 'status', 'disconnected'],
  ['settings', 'account', 'connectedApps', 'github', 'status', 'configMissing'],
  ['settings', 'personalization', 'automaticWebSearch', 'title'],
  ['settings', 'personalization', 'automaticWebSearch', 'description'],
  ['settings', 'tabs', 'about'],
  ['settings', 'about', 'quickLinksLabel'],
  ['settings', 'about', 'website', 'title'],
  ['settings', 'about', 'website', 'description'],
  ['settings', 'about', 'website', 'link'],
  ['settings', 'about', 'github', 'title'],
  ['settings', 'about', 'github', 'description'],
  ['settings', 'about', 'github', 'link'],
  ['settings', 'about', 'socials', 'title'],
  ['settings', 'about', 'socials', 'description'],
  ['settings', 'about', 'socials', 'links', 'synvexTelegram'],
  ['settings', 'about', 'socials', 'links', 'youtube'],
  ['settings', 'about', 'socials', 'links', 'x'],
  ['settings', 'about', 'socials', 'links', 'telegramChannel'],
  ['settings', 'about', 'socials', 'links', 'tiktok'],
  ['settings', 'about', 'socials', 'links', 'reddit'],
  ['settings', 'about', 'policies', 'title'],
  ['settings', 'about', 'policies', 'description'],
  ['settings', 'about', 'policies', 'link'],
  ['composer', 'webSearchLabel'],
  ['composer', 'webSearchOn'],
  ['composer', 'webSearchOff'],
  ['files', 'tooMany'],
  ['files', 'unsupportedType'],
  ['files', 'emptyFile'],
  ['files', 'sizeLimit'],
  ['rail', 'statusGenerating'],
  ['rail', 'statusError'],
  ['rail', 'statusComplete'],
  ['quiz', 'correctAnswer'],
  ['quiz', 'incorrectAnswer'],
  ['spinwheel', 'spinning'],
  ['spinwheel', 'result'],
  ['beatbox', 'stepLabel'],
  ['canvas', 'markdownPreviewLabel'],
  ['canvas', 'mode', 'group'],
  ['canvas', 'mode', 'markdown'],
  ['canvas', 'mode', 'raw'],
  ['chat', 'githubDiff', 'title'],
  ['chat', 'githubDiff', 'branch'],
  ['chat', 'githubDiff', 'filesChanged'],
  ['chat', 'githubDiff', 'additions'],
  ['chat', 'githubDiff', 'deletions'],
  ['chat', 'githubDiff', 'copy'],
  ['chat', 'githubDiff', 'copied'],
  ['chat', 'githubDiff', 'download'],
  ['chat', 'githubDiff', 'openPullRequest'],
  ['chat', 'githubDiff', 'truncated'],
  ['chat', 'githubDiff', 'status', 'added'],
  ['chat', 'githubDiff', 'status', 'deleted'],
  ['chat', 'githubDiff', 'status', 'modified'],
  ['chat', 'githubDiff', 'status', 'renamed'],
  ['webSearch', 'sourcesLabel'],
  ['webSearch', 'sourcesAria'],
  ['webSearch', 'queryLabel'],
  ['webSearch', 'fragmentSources'],
  ['webSearch', 'status', 'querying'],
  ['webSearch', 'status', 'deciding'],
  ['webSearch', 'status', 'started'],
  ['webSearch', 'status', 'fetching'],
  ['webSearch', 'status', 'skipped'],
  ['webSearch', 'status', 'done'],
  ['webSearch', 'status', 'failed'],
  ['minds', 'subtitle'],
  ['minds', 'activeLabel'],
  ['minds', 'searchPlaceholder'],
  ['minds', 'tabs', 'store'],
  ['minds', 'tabs', 'mine'],
  ['minds', 'categories', 'general'],
  ['minds', 'visibility', 'private'],
  ['minds', 'errors', 'save'],
  ['minds', 'validation', 'instructions'],
  ['minds', 'editor', 'createTitle'],
  ['minds', 'editor', 'fields', 'instructions'],
  ['minds', 'editor', 'saveChanges'],
] as const;

const validationKeys = [
  'nameRequired',
  'nameLength',
  'nameInvalidCharacters',
  'usernameRequired',
  'usernameLength',
  'usernameCharset',
  'usernameStartsWith',
  'usernameTaken',
  'emailTaken',
] as const;

const localizedCorePaths = [
  ['authModal', 'fields', 'email'],
  ['common', 'copy'],
  ['common', 'close'],
  ['chat', 'editUserMessage', 'placeholder'],
  ['chat', 'editUserMessage', 'ariaLabel'],
  ['chat', 'editUserMessage', 'save'],
  ['chat', 'editUserMessage', 'cancel'],
  ['chat', 'editUserMessage', 'edit'],
  ['chat', 'githubDiff', 'title'],
  ['chat', 'githubDiff', 'branch'],
  ['chat', 'githubDiff', 'filesChanged'],
  ['chat', 'githubDiff', 'additions'],
  ['chat', 'githubDiff', 'deletions'],
  ['chat', 'githubDiff', 'copy'],
  ['chat', 'githubDiff', 'copied'],
  ['chat', 'githubDiff', 'download'],
  ['chat', 'githubDiff', 'expandFile'],
  ['chat', 'githubDiff', 'collapseFile'],
  ['chat', 'githubDiff', 'openPullRequest'],
  ['chat', 'githubDiff', 'truncated'],
  ['chat', 'githubDiff', 'status', 'added'],
  ['chat', 'githubDiff', 'status', 'deleted'],
  ['chat', 'githubDiff', 'status', 'modified'],
  ['chat', 'githubDiff', 'status', 'renamed'],
  ['chat', 'ariaLog'],
  ['chat', 'userMessageAria'],
  ['chat', 'assistantMessageAria'],
  ['chat', 'regenerate'],
  ['chat', 'audio', 'speak'],
  ['chat', 'audio', 'loading'],
  ['chat', 'audio', 'play'],
  ['chat', 'audio', 'pause'],
  ['chat', 'audio', 'progress'],
  ['chat', 'audio', 'error'],
  ['chat', 'feedback', 'like'],
  ['chat', 'feedback', 'dislike'],
  ['chat', 'feedback', 'panelTitle'],
  ['chat', 'feedback', 'reasonGroup'],
  ['chat', 'feedback', 'commentLabel'],
  ['chat', 'feedback', 'commentPlaceholder'],
  ['chat', 'feedback', 'submit'],
  ['chat', 'feedback', 'sending'],
  ['chat', 'feedback', 'sent'],
  ['chat', 'feedback', 'error'],
  ['chat', 'feedback', 'noSession'],
  ['chat', 'feedback', 'reasons', 'incorrect'],
  ['chat', 'feedback', 'reasons', 'unsafe'],
  ['chat', 'feedback', 'reasons', 'not_helpful'],
  ['chat', 'feedback', 'reasons', 'too_long'],
  ['chat', 'feedback', 'reasons', 'missing_context'],
  ['chat', 'feedback', 'reasons', 'other'],
  ['chatImage', 'messageAlt'],
  ['chatImage', 'generating'],
  ['files', 'fileFallback'],
  ['rail', 'temporaryChat'],
  ['rail', 'admin'],
  ['settings', 'account', 'connectedApps', 'title'],
  ['settings', 'account', 'connectedApps', 'description'],
  ['settings', 'account', 'connectedApps', 'github', 'description'],
  ['settings', 'account', 'connectedApps', 'github', 'connect'],
  ['settings', 'account', 'connectedApps', 'github', 'manage'],
  ['settings', 'account', 'connectedApps', 'github', 'error'],
  ['settings', 'account', 'connectedApps', 'github', 'repoCount'],
  ['settings', 'account', 'connectedApps', 'github', 'status', 'checking'],
  ['settings', 'account', 'connectedApps', 'github', 'status', 'connected'],
  ['settings', 'account', 'connectedApps', 'github', 'status', 'disconnected'],
  ['settings', 'account', 'connectedApps', 'github', 'status', 'configMissing'],
  ['settings', 'interface', 'chatPanel', 'shortcut', 'record'],
  ['settings', 'interface', 'chatPanel', 'shortcut', 'recording'],
  ['settings', 'interface', 'chatPanel', 'shortcut', 'invalid'],
  ['settings', 'interface', 'chatPanel', 'launchAtLogin', 'title'],
  ['settings', 'interface', 'chatPanel', 'launchAtLogin', 'description'],
  ['settings', 'privacy', 'title'],
  ['settings', 'privacy', 'description'],
  ['settings', 'privacy', 'serviceImprovement', 'title'],
  ['settings', 'privacy', 'serviceImprovement', 'description'],
  ['settings', 'privacy', 'exportAction'],
  ['settings', 'privacy', 'exportLoading'],
  ['settings', 'privacy', 'exportSuccess'],
  ['settings', 'privacy', 'exportError'],
  ['settings', 'privacy', 'signInForExport'],
  ['settings', 'privacy', 'policyLink', 'title'],
  ['settings', 'privacy', 'policyLink', 'description'],
  ['minds', 'tabs', 'store'],
  ['minds', 'visibility', 'store'],
  ['temporaryChat', 'title'],
  ['temporaryChat', 'badge'],
  ['temporaryChat', 'description'],
  ['translationPanel', 'translateAction'],
  ['admin', 'aiFeedback', 'likeRatio'],
  ['admin', 'aiFeedback', 'dislikeRatio'],
  ['admin', 'aiFeedback', 'total'],
] as const;

function readLocale(locale: string) {
  const filePath = path.join(localeDir, locale, 'common.json');
  return JSON.parse(readFileSync(filePath, 'utf-8')) as Record<string, unknown>;
}

function collectKeyPathSchema(
  source: Record<string, unknown>,
  prefix: readonly string[] = [],
): string[] {
  const schema: string[] = [];

  for (const [key, value] of Object.entries(source)) {
    const keyPath = [...prefix, key];
    const valueType = Array.isArray(value)
      ? 'array'
      : value === null
        ? 'null'
        : typeof value;
    schema.push(`${keyPath.join('.')}:${valueType}`);

    if (valueType === 'object') {
      schema.push(...collectKeyPathSchema(value as Record<string, unknown>, keyPath));
    }
  }

  return schema.sort();
}

function collectInterpolationTokens(source: Record<string, unknown>) {
  const tokens = new Map<string, string[]>();

  const visit = (value: unknown, prefix: readonly string[]) => {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      for (const [key, nestedValue] of Object.entries(value)) {
        visit(nestedValue, [...prefix, key]);
      }
      return;
    }

    if (typeof value !== 'string') return;
    const matches = Array.from(value.matchAll(/\{\{\s*([^},\s]+)[^}]*\}\}/g));
    tokens.set(
      prefix.join('.'),
      matches.map((match) => match[1]).sort(),
    );
  };

  visit(source, []);
  return tokens;
}

function getValue(source: Record<string, unknown>, keyPath: readonly string[]) {
  return keyPath.reduce<unknown>((current, key) => {
    if (!current || typeof current !== 'object' || !(key in current)) {
      throw new Error(`Missing key: ${keyPath.join('.')}`);
    }

    return (current as Record<string, unknown>)[key];
  }, source);
}

describe('locale schema coverage', () => {
  it('matches the complete English key-path schema in every locale', () => {
    const englishSchema = collectKeyPathSchema(readLocale('en'));

    for (const locale of locales) {
      const localeSchema = collectKeyPathSchema(readLocale(locale));
      expect(localeSchema, `${locale} must match the complete en locale schema`).toEqual(englishSchema);
    }
  });

  it('preserves every English interpolation token', () => {
    const englishTokens = collectInterpolationTokens(readLocale('en'));

    for (const locale of locales) {
      const localeTokens = collectInterpolationTokens(readLocale(locale));
      for (const [keyPath, expectedTokens] of englishTokens) {
        expect(
          localeTokens.get(keyPath),
          `${locale}.${keyPath} must preserve interpolation tokens`,
        ).toEqual(expectedTokens);
      }
    }
  });
});

describe('core locale translation quality', () => {
  it('does not fall back to English for core end-user UI strings', () => {
    const english = readLocale('en');

    for (const locale of qualityPassLocales) {
      const data = readLocale(locale);

      for (const keyPath of localizedCorePaths) {
        expect(
          getValue(data, keyPath),
          `${locale}.${keyPath.join('.')} must be localized`,
        ).not.toBe(getValue(english, keyPath));
      }
    }
  });
});

describe('account locale coverage', () => {
  it('has localized account settings strings without placeholder question marks', () => {
    for (const locale of locales) {
      const data = readLocale(locale);

      for (const keyPath of requiredTextPaths) {
        const value = getValue(data, keyPath);
        expect(typeof value).toBe('string');
        expect(String(value)).not.toContain('???');
        expect(String(value)).not.toMatch(/\?\?+/);
      }
    }
  });

  it('includes localized validation messages for all account fields', () => {
    for (const locale of locales) {
      const data = readLocale(locale);
      const validation = getValue(data, ['settings', 'account', 'validation']) as Record<string, unknown>;

      for (const key of validationKeys) {
        expect(typeof validation[key]).toBe('string');
        expect(String(validation[key])).toBeTruthy();
        expect(String(validation[key])).not.toContain('???');
      }
    }
  });
});
