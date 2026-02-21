import { useState, useEffect, useCallback } from 'react';
import { useURLRouter } from './useURLRouter';


export const useSettingsModal = () => {
    const { isSettingsView, clearHash, getSettingsTab } = useURLRouter();
    const [isOpen, setIsOpen] = useState(() => {
        const parts = window.location.hash.slice(1).split('/').filter(p => p);
        return parts.length > 0 && parts[0] === 'settings';
    });
    useEffect(() => {
        const handleHashChange = () => {
            if (isSettingsView()) {
                setIsOpen(true);
            } else {
                setIsOpen(false);
            }
        };

        window.addEventListener('hashchange', handleHashChange);
        return () => window.removeEventListener('hashchange', handleHashChange);
    }, [isSettingsView]);
    const openSettings = useCallback(() => {
        setIsOpen(true);
    }, []);
    const closeSettings = useCallback(() => {
        setIsOpen(false);
        clearHash();
    }, [clearHash]);
    const closeAndOpenAuth = useCallback(() => {
        closeSettings();
        return true;
    }, [closeSettings]);

    return {
        isOpen,
        openSettings,
        closeSettings,
        closeAndOpenAuth,
        currentTab: getSettingsTab()
    };
};


