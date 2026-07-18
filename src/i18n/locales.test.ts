import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const localeDir = path.resolve(process.cwd(), 'src/i18n/locales');
const locales = ['ar', 'bn', 'en', 'es', 'fr', 'hi', 'pt', 'ru', 'zh'] as const;

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

function readLocale(locale: string) {
  const filePath = path.join(localeDir, locale, 'common.json');
  return JSON.parse(readFileSync(filePath, 'utf-8'));
}

function getValue(source: Record<string, unknown>, keyPath: readonly string[]) {
  return keyPath.reduce<unknown>((current, key) => {
    if (!current || typeof current !== 'object' || !(key in current)) {
      throw new Error(`Missing key: ${keyPath.join('.')}`);
    }

    return (current as Record<string, unknown>)[key];
  }, source);
}

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
