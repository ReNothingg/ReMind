import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from './AuthContext';
import { authService } from '../services/auth';
import { DEFAULT_LANGUAGE, LANGUAGE_STORAGE_KEY, normalizeLanguage } from '../i18n/index';

const SettingsContext = createContext(null);

const detectInterfaceLanguage = () => {
    const hasStorage = typeof localStorage !== 'undefined';
    let storedInterfaceLanguage;
    if (hasStorage) {
        try {
            storedInterfaceLanguage = JSON.parse(localStorage.getItem('settings_interface_language'));
        } catch {
            storedInterfaceLanguage = null;
        }
    }

    if (storedInterfaceLanguage) {
        return normalizeLanguage(storedInterfaceLanguage);
    }

    if (hasStorage) {
        try {
            const savedI18n = localStorage.getItem(LANGUAGE_STORAGE_KEY);
            if (savedI18n) return normalizeLanguage(savedI18n);
        } catch {
        }
    }

    if (typeof navigator !== 'undefined' && navigator.language) {
        return normalizeLanguage(navigator.language);
    }

    return normalizeLanguage(DEFAULT_LANGUAGE);
};

const DEFAULT_SETTINGS = {
    theme: 'light',
    accentColor: 'white',
    renderMarkdown: true,
    renderUserMarkdown: false,
    codeWrap: true,
    compactMode: false,
    showChatPreview: true,
    showSuggestions: true,
    autocomplete: true,
    autoscroll: true,
    notifyOnThinkingDone: false,
    requireCtrlEnterToSend: false,
    snowBackground: false,
    autoSave: true,
    fontFamily: "'Nunito', 'SF Pro Text', 'Ubuntu', 'Segoe UI', sans-serif",
    fontSize: '12px',
    keyboardSupport: true,
    highContrast: false,
    interface_language: detectInterfaceLanguage(),
    personalization_instructions: '',
    personalization_nickname: '',
    personalization_profession: '',
    personalization_more: ''
};
const ACCENT_PALETTES = {
    blue: [120, 156, 255],
    green: [46, 204, 113],
    yellow: [241, 196, 15],
    pink: [231, 84, 128],
    orange: [230, 126, 34],
    white: [220, 220, 220],
    black: [28, 28, 30],
    red: [239, 68, 68],
    purple: [139, 92, 246],
    teal: [20, 184, 166],
    cyan: [6, 182, 212]
};

const DB_FIELD_MAP = {
    theme: 'theme',
    interface_language: 'language'
};
const BASE_KEYS = new Set(Object.keys(DB_FIELD_MAP));

export const SettingsProvider = ({ children }) => {
    const { isAuthenticated } = useAuth();

    const [settings, setSettings] = useState(() => {
        const saved = {};
        Object.keys(DEFAULT_SETTINGS).forEach(key => {
            const item = localStorage.getItem(`settings_${key}`);
            if (item !== null) {
                try {
                    saved[key] = JSON.parse(item);
                } catch (e) {
                    console.warn(`Failed to load setting ${key}:`, e);
                }
            }
        });
        const merged = { ...DEFAULT_SETTINGS, ...saved };

        const normalizedInterfaceLanguage = normalizeLanguage(merged.interface_language);
        merged.interface_language = normalizedInterfaceLanguage;
        if (typeof localStorage !== 'undefined') {
            try {
                const storedInterfaceLanguage = localStorage.getItem('settings_interface_language');
                const storedValue = storedInterfaceLanguage ? JSON.parse(storedInterfaceLanguage) : null;
                if (storedValue !== normalizedInterfaceLanguage) {
                    localStorage.setItem('settings_interface_language', JSON.stringify(normalizedInterfaceLanguage));
                }
            } catch {
            }
        }
        if (typeof merged.fontSize === 'string' && merged.fontSize.trim().endsWith('rem')) {
            const remMap = {
                '0.875rem': '12px',
                '1rem': '14px',
                '1.125rem': '16px',
                '1.25rem': '18px'
            };
            merged.fontSize = remMap[merged.fontSize.trim()] || DEFAULT_SETTINGS.fontSize;
        }

        return merged;
    });

    const saveDebounceTimerRef = useRef(null);
    const pendingSavesRef = useRef({});
    const lastAuthStateRef = useRef(isAuthenticated);
    const loadSettingsFromDB = useCallback(async () => {
        if (!isAuthenticated) return;

        try {
            const dbSettings = await authService.getSettings();
            if (dbSettings && !dbSettings.error) {
                const newSettings = { ...DEFAULT_SETTINGS };
                if (dbSettings.theme) newSettings.theme = dbSettings.theme;
                if (dbSettings.language) newSettings.interface_language = dbSettings.language;
                if (dbSettings.settings_data) {
                    Object.keys(DEFAULT_SETTINGS).forEach(key => {
                        if (!BASE_KEYS.has(key) && dbSettings.settings_data[key] !== undefined) {
                            newSettings[key] = dbSettings.settings_data[key];
                        }
                    });
                }

                setSettings(newSettings);
                return;
            }
        } catch (error) {
            console.warn('Failed to load settings from DB, falling back to localStorage:', error);
        }
    }, [isAuthenticated]);
    const saveToDB = useCallback(async () => {
        if (!isAuthenticated || Object.keys(pendingSavesRef.current).length === 0) {
            return;
        }

        try {
            const currentSettings = await authService.getSettings();
            const existingData = (currentSettings && !currentSettings.error && currentSettings.settings_data)
                ? currentSettings.settings_data
                : {};
            const mergedSettings = { ...existingData };

            Object.entries(pendingSavesRef.current).forEach(([key, value]) => {
                if (!BASE_KEYS.has(key)) {
                    mergedSettings[key] = value;
                }
            });

            const payload = { settings_data: mergedSettings };
            Object.entries(DB_FIELD_MAP).forEach(([localKey, dbKey]) => {
                if (pendingSavesRef.current[localKey] !== undefined) {
                    payload[dbKey] = pendingSavesRef.current[localKey];
                }
            });

            await authService.updateSettings(payload);
            pendingSavesRef.current = {};
        } catch (error) {
            console.error('Failed to save settings to DB:', error);
            Object.entries(pendingSavesRef.current).forEach(([key, value]) => {
                try {
                    localStorage.setItem(`settings_${key}`, JSON.stringify(value));
                } catch (e) {
                    console.warn(`Could not save setting ${key} to localStorage:`, e);
                }
            });
        }
    }, [isAuthenticated]);
    const applySetting = useCallback((key, value) => {
        switch (key) {
            case 'theme': {
                const actualTheme = value === 'system'
                    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
                    : value;
                document.documentElement.setAttribute('data-theme', actualTheme);
                break;
            }
            case 'accentColor': {
                if (!value) return;
                document.documentElement.setAttribute('data-accent-color', value);
                const raw = ACCENT_PALETTES[value] || ACCENT_PALETTES['blue'];
                if (Array.isArray(raw) && raw.length === 3) {
                    const rawStr = raw.join(', ');
                    document.documentElement.style.setProperty('--color-accent-raw', rawStr);
                    document.documentElement.style.setProperty('--color-accent', `rgb(${rawStr})`);
                    document.documentElement.style.setProperty('--color-border-focus', `rgba(${rawStr}, 0.45)`);
                }
                break;
            }
            case 'codeWrap':
                document.body.classList.toggle('code-wrap-enabled', value);
                break;
            case 'compactMode':
                document.body.classList.toggle('compact-mode', value);
                break;
            case 'snowBackground':
                document.body.classList.toggle('snow-background-enabled', value);
                break;
            case 'fontFamily':
                document.documentElement.style.setProperty('--font-family-main', value);
                break;
            case 'fontSize':
                document.documentElement.style.fontSize = value;
                break;
            case 'highContrast':
                document.body.classList.toggle('high-contrast', value);
                break;
        }
    }, []);
    useEffect(() => {
        Object.entries(settings).forEach(([key, value]) => {
            applySetting(key, value);
        });
    }, [settings, applySetting]);
    useEffect(() => {
        if (settings.theme !== 'system') return;

        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        const handleChange = () => {
            applySetting('theme', 'system');
        };

        mediaQuery.addEventListener('change', handleChange);
        return () => mediaQuery.removeEventListener('change', handleChange);
    }, [settings.theme, applySetting]);
    useEffect(() => {
        const prevAuthState = lastAuthStateRef.current;
        lastAuthStateRef.current = isAuthenticated;

        if (isAuthenticated && !prevAuthState) {
            setTimeout(() => loadSettingsFromDB(), 0);
        } else if (!isAuthenticated && prevAuthState) {
            pendingSavesRef.current = {};
        }
    }, [isAuthenticated, loadSettingsFromDB]);
    useEffect(() => {
        if (isAuthenticated) {
            setTimeout(() => loadSettingsFromDB(), 0);
        }
        const params = new URLSearchParams(window.location.search);
        if (params.get('theme')) {
            const theme = decodeURIComponent(params.get('theme'));
            if (['light', 'dark', 'system'].includes(theme)) {
                updateSetting('theme', theme);
            }
        }
        if (params.get('accent')) {
            const accent = decodeURIComponent(params.get('accent'));
            updateSetting('accentColor', accent);
        }
    }, []); // Только при монтировании

    const updateSetting = useCallback((key, value) => {
        setSettings(prev => ({ ...prev, [key]: value }));
        try {
            localStorage.setItem(`settings_${key}`, JSON.stringify(value));
        } catch (e) {
            console.warn(`Could not save setting ${key}:`, e);
        }
        if (isAuthenticated) {
            pendingSavesRef.current[key] = value;
            clearTimeout(saveDebounceTimerRef.current);
            saveDebounceTimerRef.current = setTimeout(() => {
                saveToDB();
            }, 500);
        }
    }, [isAuthenticated, saveToDB]);

    return (
        <SettingsContext.Provider value={{ settings, updateSetting }}>
            {children}
        </SettingsContext.Provider>
    );
};

export const useSettings = () => useContext(SettingsContext);
