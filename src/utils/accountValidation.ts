export type AccountFieldName = 'name' | 'username' | 'email' | 'password';
export type AccountFieldErrors = Partial<Record<AccountFieldName, string>>;

type TranslateFunction = (key: string, options?: Record<string, unknown>) => string;

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

export function localizeAccountError(
    message: string | undefined,
    field: AccountFieldName | undefined,
    t: TranslateFunction
): { fieldErrors: AccountFieldErrors; message?: string } {
    if (!message) {
        return { fieldErrors: {} };
    }

    const fieldErrors: AccountFieldErrors = {};

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

    return { fieldErrors, message };
}

export function firstAccountFieldError(errors: AccountFieldErrors): string | undefined {
    return errors.name || errors.username || errors.email || errors.password;
}
