export type AccountFieldName = 'name' | 'username' | 'email' | 'password';
export type AccountFieldErrors = Partial<Record<AccountFieldName, string>>;

type TranslateFunction = (key: string, options?: Record<string, unknown>) => string;

export const ACCOUNT_PASSWORD_MIN_LENGTH = 8;

export function getAccountPasswordRequirements(value: string) {
    const password = String(value || '');

    return {
        hasMinimumLength: password.length >= ACCOUNT_PASSWORD_MIN_LENGTH,
        hasDigit: /\d/.test(password),
        hasSpecialCharacter: /[^\sA-Za-z0-9]/.test(password),
    };
}

export function getAccountPasswordStrength(value: string) {
    if (!value) {
        return { score: 0, level: 'empty' } as const;
    }

    let score = 0;
    const hasLower = /[a-z]/.test(value);
    const hasUpper = /[A-Z]/.test(value);
    const hasNumber = /\d/.test(value);
    const hasSymbol = /[^\sA-Za-z0-9]/.test(value);
    const uniqueCharacters = new Set(value).size;

    if (value.length >= 8) score += 1;
    if (value.length >= 12) score += 1;
    if (hasLower && hasUpper) score += 1;
    if (hasNumber) score += 1;
    if (hasSymbol) score += 1;
    if (value.length >= 8 && uniqueCharacters < 5) score -= 1;

    score = Math.max(1, Math.min(score, 4));

    // A password that registration will reject must not be presented as strong.
    if (!Object.values(getAccountPasswordRequirements(value)).every(Boolean)) {
        score = Math.min(score, 1);
    }

    if (score >= 4) return { score, level: 'strong' } as const;
    if (score === 3) return { score, level: 'good' } as const;
    if (score === 2) return { score, level: 'fair' } as const;
    return { score, level: 'weak' } as const;
}

export function validateAccountPassword(value: string, t: TranslateFunction): string | undefined {
    const password = String(value || '');
    const requirements = getAccountPasswordRequirements(password);

    if (!password) {
        return t('authModal.messages.passwordRequired');
    }
    if (!requirements.hasMinimumLength) {
        return t('authModal.messages.passwordMinLength', { count: ACCOUNT_PASSWORD_MIN_LENGTH });
    }
    if (!requirements.hasDigit) {
        return t('authModal.messages.passwordDigitRequired');
    }
    if (!requirements.hasSpecialCharacter) {
        return t('authModal.messages.passwordSpecialRequired');
    }

    return undefined;
}

function normalizeValue(value: string): string {
    return String(value || '').trim();
}

function containsUnsafeNameCharacters(value: string): boolean {
    for (const char of value || '') {
        const code = char.charCodeAt(0);
        if (code <= 31 || code === 127 || char === '<' || char === '>') {
            return true;
        }
    }

    return false;
}

export function validateAccountName(
    value: string,
    t: TranslateFunction,
    { required = false }: { required?: boolean } = {}
): string | undefined {
    const normalized = normalizeValue(value);

    if (!normalized) {
        return required ? t('settings.account.validation.nameRequired') : undefined;
    }

    if (normalized.length > 100) {
        return t('settings.account.validation.nameLength');
    }

    if (containsUnsafeNameCharacters(normalized)) {
        return t('settings.account.validation.nameInvalidCharacters');
    }

    return undefined;
}

export function validateUsername(value: string, t: TranslateFunction): string | undefined {
    const normalized = normalizeValue(value);

    if (!normalized) {
        return t('settings.account.validation.usernameRequired');
    }

    if (normalized.length < 3 || normalized.length > 50) {
        return t('settings.account.validation.usernameLength');
    }

    if (!/^[a-zA-Z0-9_-]+$/.test(normalized)) {
        return t('settings.account.validation.usernameCharset');
    }

    if (/^[_-]/.test(normalized)) {
        return t('settings.account.validation.usernameStartsWith');
    }

    return undefined;
}

function localizeUsernameError(message: string, t: TranslateFunction): string {
    if (message.includes('already taken')) {
        return t('settings.account.validation.usernameTaken');
    }
    if (message.includes('non-empty string')) {
        return t('settings.account.validation.usernameRequired');
    }
    if (message.includes('3-50 characters')) {
        return t('settings.account.validation.usernameLength');
    }
    if (message.includes('letters, numbers, underscore, and hyphen')) {
        return t('settings.account.validation.usernameCharset');
    }
    if (message.includes('cannot start with underscore or hyphen')) {
        return t('settings.account.validation.usernameStartsWith');
    }
    return message;
}

function localizeNameError(message: string, t: TranslateFunction): string {
    if (message.includes('non-empty string')) {
        return t('settings.account.validation.nameRequired');
    }
    if (message.includes('1-100 characters')) {
        return t('settings.account.validation.nameLength');
    }
    if (message.includes('contains invalid characters')) {
        return t('settings.account.validation.nameInvalidCharacters');
    }
    return message;
}

function localizePasswordError(message: string, t: TranslateFunction): string {
    if (message.includes('non-empty string')) {
        return t('authModal.messages.passwordRequired');
    }
    if (message.includes('too long')) {
        return t('authModal.messages.passwordTooLong');
    }
    if (message.includes('at least') && message.includes('characters')) {
        return t('authModal.messages.passwordMinLength', { count: ACCOUNT_PASSWORD_MIN_LENGTH });
    }
    if (message.includes('at least one digit')) {
        return t('authModal.messages.passwordDigitRequired');
    }
    if (message.includes('at least one special character')) {
        return t('authModal.messages.passwordSpecialRequired');
    }
    return message;
}

export function localizeAccountError(
    message: string | undefined,
    field: AccountFieldName | undefined,
    t: TranslateFunction
): { fieldErrors: AccountFieldErrors; message?: string } {
    if (!message) {
        return { fieldErrors: {} };
    }

    const fieldErrors: AccountFieldErrors = {};

    if (message === 'confirmation_delivery_failed') {
        return { fieldErrors, message: t('authModal.messages.requestError') };
    }

    if (field === 'username' || message.startsWith('Username')) {
        const localized = localizeUsernameError(message, t);
        fieldErrors.username = localized;
        return { fieldErrors, message: localized };
    }

    if (field === 'name' || message.startsWith('Name')) {
        const localized = localizeNameError(message, t);
        fieldErrors.name = localized;
        return { fieldErrors, message: localized };
    }

    if (field === 'email' && message.includes('Email')) {
        const localized = t('settings.account.validation.emailTaken');
        fieldErrors.email = localized;
        return { fieldErrors, message: localized };
    }

    if (field === 'password' || message.startsWith('Password')) {
        const localized = localizePasswordError(message, t);
        fieldErrors.password = localized;
        return { fieldErrors, message: localized };
    }

    return { fieldErrors, message };
}

export function firstAccountFieldError(errors: AccountFieldErrors): string | undefined {
    return errors.name || errors.username || errors.email || errors.password;
}
