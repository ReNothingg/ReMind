import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { authService } from '../services/auth';
import type { AuthCheckResult, AuthUser } from '../services/auth';

type AuthContextValue = {
    user: AuthUser | null;
    isAuthenticated: boolean;
    loading: boolean;
    login: typeof authService.login;
    logout: typeof authService.logout;
    checkAuth: () => Promise<AuthCheckResult>;
    updateProfile: typeof authService.updateProfile;
    deleteAccount: typeof authService.deleteAccount;
    getSettings: typeof authService.getSettings;
    updateSettings: typeof authService.updateSettings;
    getPreferences: typeof authService.getPreferences;
    updatePreferences: typeof authService.updatePreferences;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export const AuthProvider = ({ children }: { children: ReactNode }) => {
    const [user, setUser] = useState<AuthUser | null>(null);
    const [isAuthenticated, setIsAuthenticated] = useState(false);
    const [loading, setLoading] = useState(true);

    const checkAuth = async (): Promise<AuthCheckResult> => {
        try {
            const data = await authService.checkAuth();
            setIsAuthenticated(data.authenticated);
            setUser(data.user || null);
            return data;
        } catch (e) {
            console.error('Auth check error:', e);
            setIsAuthenticated(false);
            setUser(null);
            return { authenticated: false, user: null };
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        void checkAuth();
    }, []);

    const login: typeof authService.login = async (email, pass, token) => {
        const res = await authService.login(email, pass, token);
        if (res.success) {
            const authState = await checkAuth();
            if (!authState.authenticated) {
                return {
                    success: false,
                    error: 'Не удалось подтвердить сессию после входа. Проверьте, что cookies разрешены для этого сайта.',
                };
            }
            window.location.reload();
        }
        return res;
    };

    const logout: typeof authService.logout = async () => {
        const res = await authService.logout();
        setIsAuthenticated(false);
        setUser(null);
        if (res.success) {
            window.location.reload();
        }
        return res;
    };

    const deleteAccount: typeof authService.deleteAccount = async () => {
        const res = await authService.deleteAccount();
        if (res.success) {
            setIsAuthenticated(false);
            setUser(null);
        }
        return res;
    };

    const updateProfile: typeof authService.updateProfile = async (profileData) => {
        const res = await authService.updateProfile(profileData);
        if (res.success && res.user) {
            setUser(res.user);
        }
        return res;
    };

    const getSettings: typeof authService.getSettings = async () => {
        return await authService.getSettings();
    };

    const updateSettings: typeof authService.updateSettings = async (settingsData) => {
        return await authService.updateSettings(settingsData);
    };

    const getPreferences: typeof authService.getPreferences = async () => {
        return await authService.getPreferences();
    };

    const updatePreferences: typeof authService.updatePreferences = async (preferences) => {
        return await authService.updatePreferences(preferences);
    };

    return (
        <AuthContext.Provider
            value={{
                user,
                isAuthenticated,
                loading,
                login,
                logout,
                checkAuth,
                updateProfile,
                deleteAccount,
                getSettings,
                updateSettings,
                getPreferences,
                updatePreferences,
            }}
        >
            {children}
        </AuthContext.Provider>
    );
};

// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within AuthProvider');
    }
    return context;
};
