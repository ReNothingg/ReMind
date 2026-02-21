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
        } catch (e) {
            console.error('Auth check error:', e);
            setIsAuthenticated(false);
            setUser(null);
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
            await checkAuth(); // Обновить состояние
            window.location.reload(); // Для сброса серверных сессий Flask, как в оригинале
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
            getSettings,
            updateSettings,
            getPreferences,
            updatePreferences
        }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => useContext(AuthContext);