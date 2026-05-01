import React, { createContext, useContext, useState, useEffect } from 'react';
import { authService } from '../services/auth';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [isAuthenticated, setIsAuthenticated] = useState(false);
    const [loading, setLoading] = useState(true);

    const checkAuth = async () => {
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
        checkAuth();
    }, []);

    const login = async (email, pass, token) => {
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

    const logout = async () => {
        const res = await authService.logout();
        setIsAuthenticated(false);
        setUser(null);
        if (res.success) {
            window.location.reload();
        }
        return res;
    };

    const deleteAccount = async () => {
        const res = await authService.deleteAccount();
        if (res.success) {
            setIsAuthenticated(false);
            setUser(null);
        }
        return res;
    };

    const updateProfile = async (profileData) => {
        const res = await authService.updateProfile(profileData);
        if (res.success && res.user) {
            setUser(res.user);
        }
        return res;
    };

    const getSettings = async () => {
        return await authService.getSettings();
    };

    const updateSettings = async (settingsData) => {
        return await authService.updateSettings(settingsData);
    };

    const getPreferences = async () => {
        return await authService.getPreferences();
    };

    const updatePreferences = async (preferences) => {
        return await authService.updatePreferences(preferences);
    };

    return (
        <AuthContext.Provider value={{
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
            updatePreferences
        }}>
            {children}
        </AuthContext.Provider>
    );
};

// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = () => useContext(AuthContext);
