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
