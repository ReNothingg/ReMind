import { apiAuthCheck, apiAuthLogin } from './openapiClient';
import { ApiClientError, extractApiErrorMessage, requestJson } from './http';
import type { AccountFieldName } from '../utils/accountValidation';

type AuthUser = {
    id: number;
    username: string;
    name?: string | null;
    email: string;
    is_confirmed: boolean;
    created_at?: string | null;
    oauth_provider?: string | null;
};

type AuthCheckResult = {
    authenticated: boolean;
    user: AuthUser | null;
};

type LoginResult =
    | { success: true; message: string; user: AuthUser }
    | { success: false; error: string };

type RegisterResponse = {
    message?: string;
    user_id?: number;
    error?: string;
    field?: AccountFieldName;
};

type LogoutResponse = {
    success: boolean;
    message?: string;
    error?: string;
};

type ProfileResponse = {
    user?: AuthUser;
    error?: string;
    field?: AccountFieldName;
    [key: string]: unknown;
};

type SettingsResponse = {
    theme?: string;
    language?: string;
    settings_data?: Record<string, unknown>;
    settings?: Record<string, unknown>;
    error?: string;
    [key: string]: unknown;
};

type PreferencesResponse = {
    preferences?: Record<string, unknown>;
};

type FavoritesResponse = {
    favorites?: string[];
};

type DeleteAccountResponse = {
    deleted?: {
        account_deleted?: boolean;
        [key: string]: unknown;
    };
    error?: string;
};

type SuccessResult<T extends string, TValue> =
    | { success: true } & Record<T, TValue>
    | { success: false; error?: string; field?: AccountFieldName };

const MAX_FIELD_LENGTH = 100;

function validateLength(value: string, message: string): string | null {
    return value.length > MAX_FIELD_LENGTH ? message : null;
}

function logFailure(scope: string, error: unknown): void {
    console.error(`${scope} failed:`, error);
}

function isGenericTransportMessage(message: string): boolean {
    return /^HTTP error: \d+$/.test(message.trim());
}

function buildFailureResult(
    error?: string,
    field?: AccountFieldName
): { success: false; error?: string; field?: AccountFieldName } {
    return error ? { success: false, error, ...(field ? { field } : {}) } : { success: false };
}

function extractOptionalField(error: unknown): AccountFieldName | undefined {
    if (!(error instanceof ApiClientError) || !error.data || typeof error.data !== 'object') {
        return undefined;
    }

    const field = (error.data as { field?: unknown }).field;
    return typeof field === 'string' ? (field as AccountFieldName) : undefined;
}

function extractOptionalErrorMessage(error: unknown, fallback: string): string | undefined {
    const message = extractApiErrorMessage(error, fallback);
    if (!message || message === fallback || isGenericTransportMessage(message)) {
        return undefined;
    }
    return message;
}

async function requestAuthJson<TResponse>(
    path: string,
    options: RequestInit = {}
): Promise<TResponse> {
    return requestJson<TResponse>(path, options);
}

export const authService = {
    async checkAuth(): Promise<AuthCheckResult> {
        try {
            const data = await apiAuthCheck();
            return { authenticated: data.authenticated, user: data.user || null };
        } catch (error) {
            logFailure('Auth check', error);
            return { authenticated: false, user: null };
        }
    },

    async login(
        email: string,
        password: string,
        turnstileResponse: string | null
    ): Promise<LoginResult> {
        try {
            const data = await apiAuthLogin({
                email,
                password,
                turnstile_response: turnstileResponse,
            });
            return { success: true, message: data.message, user: data.user };
        } catch (error) {
            logFailure('Login', error);
            return {
                success: false,
                error: extractApiErrorMessage(error, 'Ошибка при входе'),
            };
        }
    },

    async register(
        name: string,
        username: string,
        email: string,
        password: string,
        turnstileResponse: string | null
    ): Promise<
        | { success: true; message?: string; user_id?: number }
        | { success: false; error: string; field?: AccountFieldName }
    > {
        const nameError = validateLength(name, 'Name must not exceed 100 characters');
        if (nameError) {
            return { success: false, error: nameError, field: 'name' };
        }

        const usernameError = validateLength(
            username,
            'Имя пользователя не должно превышать 100 символов'
        );
        if (usernameError) {
            return { success: false, error: usernameError, field: 'username' };
        }

        const emailError = validateLength(email, 'Email не должен превышать 100 символов');
        if (emailError) {
            return { success: false, error: emailError, field: 'email' };
        }

        const passwordError = validateLength(
            password,
            'Пароль не должен превышать 100 символов'
        );
        if (passwordError) {
            return { success: false, error: passwordError, field: 'password' };
        }

        try {
            const data = await requestAuthJson<RegisterResponse>('/api/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name,
                    username,
                    email,
                    password,
                    turnstile_response: turnstileResponse,
                }),
            });

            const result: { success: true; message?: string; user_id?: number } = {
                success: true,
            };
            if (data.message !== undefined) {
                result.message = data.message;
            }
            if (data.user_id !== undefined) {
                result.user_id = data.user_id;
            }
            return result;
        } catch (error) {
            logFailure('Register', error);
            const registerError = extractApiErrorMessage(error, 'Registration failed');
            const registerField = extractOptionalField(error);
            if (registerField) {
                return { success: false, error: registerError, field: registerField };
            }
            return { success: false, error: extractApiErrorMessage(error, 'Ошибка при регистрации') };
        }
    },

    async logout(): Promise<LogoutResponse> {
        try {
            await requestAuthJson<unknown>('/api/auth/logout', {
                method: 'POST',
            });
            return { success: true, message: 'Успешный выход' };
        } catch (error) {
            logFailure('Logout', error);
            return { success: false, error: 'Ошибка при выходе' };
        }
    },

    async deleteAccount(): Promise<SuccessResult<'deleted', NonNullable<DeleteAccountResponse['deleted']>>> {
        try {
            const data = await requestAuthJson<DeleteAccountResponse>('/api/privacy/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ delete_account: true }),
            });

            if (data.deleted) {
                return { success: true, deleted: data.deleted };
            }

            return buildFailureResult(data.error);
        } catch (error) {
            logFailure('Delete account', error);
            return {
                success: false,
                error: extractApiErrorMessage(error, 'Failed to delete account'),
            };
        }
    },

    async getProfile(): Promise<ProfileResponse> {
        try {
            return await requestAuthJson<ProfileResponse>('/api/auth/profile', {
                method: 'GET',
            });
        } catch (error) {
            logFailure('Get profile', error);
            return { error: extractOptionalErrorMessage(error, 'Failed to get profile') || 'Failed to get profile' };
        }
    },

    async updateProfile(
        profileData: Record<string, unknown>
    ): Promise<SuccessResult<'user', AuthUser>> {
        try {
            const data = await requestAuthJson<ProfileResponse>('/api/auth/profile', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(profileData),
            });

            if (data.user) {
                return { success: true, user: data.user };
            }

            return buildFailureResult(data.error, data.field);
        } catch (error) {
            logFailure('Update profile', error);
            const field = extractOptionalField(error);
            return {
                success: false,
                error: extractApiErrorMessage(error, 'Failed to update profile'),
                ...(field ? { field } : {}),
            };
        }
    },

    async getSettings(): Promise<SettingsResponse> {
        try {
            return await requestAuthJson<SettingsResponse>('/api/auth/settings', {
                method: 'GET',
            });
        } catch (error) {
            logFailure('Get settings', error);
            return { error: extractOptionalErrorMessage(error, 'Failed to get settings') || 'Failed to get settings' };
        }
    },

    async updateSettings(
        settingsData: Record<string, unknown>
    ): Promise<SuccessResult<'settings', Record<string, unknown>>> {
        try {
            const data = await requestAuthJson<SettingsResponse>('/api/auth/settings', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settingsData),
            });

            if (data.settings) {
                return { success: true, settings: data.settings };
            }

            return {
                success: false,
                error:
                    typeof data.error === 'string'
                        ? data.error
                        : 'Ошибка при обновлении настроек',
            };
        } catch (error) {
            logFailure('Update settings', error);
            return {
                success: false,
                error: extractApiErrorMessage(error, 'Ошибка при обновлении настроек'),
            };
        }
    },

    async getPreferences(): Promise<Record<string, unknown>> {
        try {
            const data = await requestAuthJson<PreferencesResponse>('/api/user/preferences', {
                method: 'GET',
            });
            return data.preferences || {};
        } catch (error) {
            logFailure('Get preferences', error);
            return {};
        }
    },

    async updatePreferences(
        preferences: Record<string, unknown>
    ): Promise<SuccessResult<'preferences', Record<string, unknown>>> {
        try {
            const data = await requestAuthJson<PreferencesResponse>('/api/user/preferences', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(preferences),
            });

            return { success: true, preferences: data.preferences || {} };
        } catch (error) {
            logFailure('Update preferences', error);
            return buildFailureResult(
                extractOptionalErrorMessage(error, 'Failed to update preferences')
            );
        }
    },

    async getFavorites(): Promise<string[]> {
        try {
            const data = await requestAuthJson<FavoritesResponse>('/api/user/favorites', {
                method: 'GET',
            });
            return data.favorites || [];
        } catch (error) {
            logFailure('Get favorites', error);
            return [];
        }
    },

    async addFavorite(sessionId: string): Promise<SuccessResult<'favorites', string[]>> {
        try {
            const data = await requestAuthJson<FavoritesResponse>('/api/user/favorites', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId }),
            });

            return { success: true, favorites: data.favorites || [] };
        } catch (error) {
            logFailure('Add favorite', error);
            return buildFailureResult(
                extractOptionalErrorMessage(error, 'Failed to add favorite')
            );
        }
    },

    async removeFavorite(sessionId: string): Promise<SuccessResult<'favorites', string[]>> {
        try {
            const data = await requestAuthJson<FavoritesResponse>('/api/user/favorites', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId }),
            });

            return { success: true, favorites: data.favorites || [] };
        } catch (error) {
            logFailure('Remove favorite', error);
            return buildFailureResult(
                extractOptionalErrorMessage(error, 'Failed to remove favorite')
            );
        }
    },
};
