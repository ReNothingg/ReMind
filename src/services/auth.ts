import { apiService, getCsrfToken } from './api';

const buildCsrfHeaders = (headers = {}) => {
    const token = getCsrfToken();
    if (!token) return headers;
    return { ...headers, 'X-CSRF-Token': token };
};

export const authService = {
    async checkAuth() {
        try {
            const response = await fetch(`${apiService.baseURL}/api/auth/check`, {
                method: 'GET',
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                return { authenticated: data.authenticated, user: data.user || null };
            }
        } catch (error) {
            console.error('Auth check failed:', error);
        }

        return { authenticated: false, user: null };
    },

    async login(email, password, turnstileResponse) {
        try {
            const response = await fetch(`${apiService.baseURL}/api/auth/login`, {
                method: 'POST',
                headers: buildCsrfHeaders({ 'Content-Type': 'application/json' }),
                credentials: 'include',
                body: JSON.stringify({ email, password, turnstile_response: turnstileResponse })
            });

            const data = await response.json();

            if (response.ok) {
                return { success: true, message: data.message, user: data.user };
            } else {
                const err = (data && (data.error?.message || data.error)) || 'Ошибка при входе';
                return { success: false, error: err };
            }
        } catch (error) {
            console.error('Login failed:', error);
            return { success: false, error: error.message };
        }
    },

    async register(username, email, password, turnstileResponse) {
        try {
            if (username.length > 100) {
                return { success: false, error: 'Имя пользователя не должно превышать 100 символов' };
            }
            if (email.length > 100) {
                return { success: false, error: 'Email не должен превышать 100 символов' };
            }
            if (password.length > 100) {
                return { success: false, error: 'Пароль не должен превышать 100 символов' };
            }

            const response = await fetch(`${apiService.baseURL}/api/auth/register`, {
                method: 'POST',
                headers: buildCsrfHeaders({ 'Content-Type': 'application/json' }),
                credentials: 'include',
                body: JSON.stringify({ username, email, password, turnstile_response: turnstileResponse })
            });

            const data = await response.json();

            if (response.ok) {
                return { success: true, message: data.message, user_id: data.user_id };
            } else {
                return { success: false, error: data.error };
            }
        } catch (error) {
            console.error('Register failed:', error);
            return { success: false, error: error.message };
        }
    },

    async logout() {
        try {
            const response = await fetch(`${apiService.baseURL}/api/auth/logout`, {
                method: 'POST',
                credentials: 'include',
                headers: buildCsrfHeaders()
            });

            if (response.ok) {
                return { success: true, message: 'Успешный выход' };
            }
        } catch (error) {
            console.error('Logout failed:', error);
        }

        return { success: false, error: 'Ошибка при выходе' };
    },

    async getProfile() {
        try {
            const response = await fetch(`${apiService.baseURL}/api/auth/profile`, {
                method: 'GET',
                credentials: 'include'
            });

            if (response.ok) {
                return await response.json();
            } else {
                return { error: 'Failed to get profile' };
            }
        } catch (error) {
            console.error('Get profile failed:', error);
            return { error: error.message };
        }
    },

    async updateProfile(profileData) {
        try {
            const response = await fetch(`${apiService.baseURL}/api/auth/profile`, {
                method: 'PUT',
                headers: buildCsrfHeaders({ 'Content-Type': 'application/json' }),
                credentials: 'include',
                body: JSON.stringify(profileData)
            });

            const data = await response.json();

            if (response.ok) {
                return { success: true, user: data.user };
            } else {
                return { success: false, error: data.error };
            }
        } catch (error) {
            console.error('Update profile failed:', error);
            return { success: false, error: error.message };
        }
    },

    async getSettings() {
        try {
            const response = await fetch(`${apiService.baseURL}/api/auth/settings`, {
                method: 'GET',
                credentials: 'include'
            });

            if (response.ok) {
                return await response.json();
            } else {
                return { error: 'Failed to get settings' };
            }
        } catch (error) {
            console.error('Get settings failed:', error);
            return { error: error.message };
        }
    },

    async updateSettings(settingsData) {
        try {
            const response = await fetch(`${apiService.baseURL}/api/auth/settings`, {
                method: 'PUT',
                headers: buildCsrfHeaders({ 'Content-Type': 'application/json' }),
                credentials: 'include',
                body: JSON.stringify(settingsData)
            });

            const data = await response.json();

            if (response.ok) {
                return { success: true, settings: data.settings };
            } else {
                const err = (data && (data.error?.message || data.error)) || 'Ошибка при обновлении настроек';
                return { success: false, error: err };
            }
        } catch (error) {
            console.error('Update settings failed:', error);
            return { success: false, error: error.message };
        }
    },

    async getPreferences() {
        try {
            const response = await fetch(`${apiService.baseURL}/api/user/preferences`, {
                method: 'GET',
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                return data.preferences || {};
            }
            return {};
        } catch (error) {
            console.error('Get preferences failed:', error);
            return {};
        }
    },

    async updatePreferences(preferences) {
        try {
            const response = await fetch(`${apiService.baseURL}/api/user/preferences`, {
                method: 'PUT',
                headers: buildCsrfHeaders({ 'Content-Type': 'application/json' }),
                credentials: 'include',
                body: JSON.stringify(preferences)
            });

            if (response.ok) {
                const data = await response.json();
                return { success: true, preferences: data.preferences || {} };
            }
            return { success: false };
        } catch (error) {
            console.error('Update preferences failed:', error);
            return { success: false, error: error.message };
        }
    },
    async getFavorites() {
        try {
            const response = await fetch(`${apiService.baseURL}/api/user/favorites`, {
                method: 'GET',
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                return data.favorites || [];
            }
            return [];
        } catch (error) {
            console.error('Get favorites failed:', error);
            return [];
        }
    },
    async addFavorite(sessionId) {
        try {
            const response = await fetch(`${apiService.baseURL}/api/user/favorites`, {
                method: 'POST',
                headers: buildCsrfHeaders({ 'Content-Type': 'application/json' }),
                credentials: 'include',
                body: JSON.stringify({ session_id: sessionId })
            });

            if (response.ok) {
                const data = await response.json();
                return { success: true, favorites: data.favorites || [] };
            }
            return { success: false };
        } catch (error) {
            console.error('Add favorite failed:', error);
            return { success: false, error: error.message };
        }
    },
    async removeFavorite(sessionId) {
        try {
            const response = await fetch(`${apiService.baseURL}/api/user/favorites`, {
                method: 'DELETE',
                headers: buildCsrfHeaders({ 'Content-Type': 'application/json' }),
                credentials: 'include',
                body: JSON.stringify({ session_id: sessionId })
            });

            if (response.ok) {
                const data = await response.json();
                return { success: true, favorites: data.favorites || [] };
            }
            return { success: false };
        } catch (error) {
            console.error('Remove favorite failed:', error);
            return { success: false, error: error.message };
        }
    }
};
