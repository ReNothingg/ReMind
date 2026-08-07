import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AuthModal from './AuthModal';

const mockAuthContext = vi.hoisted(() => ({
    login: vi.fn(),
    loginWithTelegram: vi.fn(),
    checkAuth: vi.fn(),
}));

const mockAuthService = vi.hoisted(() => ({
    register: vi.fn(),
    linkTelegram: vi.fn(),
    createTelegramLink: vi.fn(),
    getTelegramLinkStatus: vi.fn(),
}));

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string) => key,
        i18n: { language: 'en', resolvedLanguage: 'en' },
    }),
}));

vi.mock('../../context/AuthContext', () => ({
    useAuth: () => ({
        login: mockAuthContext.login,
        loginWithTelegram: mockAuthContext.loginWithTelegram,
        checkAuth: mockAuthContext.checkAuth,
        isAuthenticated: true,
    }),
}));

vi.mock('../../services/auth', () => ({
    authService: {
        register: mockAuthService.register,
        linkTelegram: mockAuthService.linkTelegram,
        createTelegramLink: mockAuthService.createTelegramLink,
        getTelegramLinkStatus: mockAuthService.getTelegramLinkStatus,
    },
}));

vi.mock('../../services/api', () => ({
    apiService: {
        baseURL: '',
    },
}));

describe('AuthModal dismissal', () => {
    let container: HTMLDivElement | null = null;
    let root: Root | null = null;

    afterEach(() => {
        if (root) {
            act(() => root?.unmount());
        }
        container?.remove();
        vi.unstubAllGlobals();
        vi.clearAllMocks();
        container = null;
        root = null;
    });

    function renderModal(onClose: () => void, initialView: 'login' | 'register' = 'register') {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(AuthModal, {
                initialView,
                onClose,
            }));
        });
    }

    it('keeps entered registration data open when the backdrop is clicked', () => {
        const onClose = vi.fn();
        renderModal(onClose);

        const overlay = container?.querySelector<HTMLElement>('.auth-modal');
        expect(overlay).not.toBeNull();

        act(() => {
            overlay?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        });

        expect(onClose).not.toHaveBeenCalled();
    });

    it('still closes from the explicit close button and Escape key', () => {
        const onClose = vi.fn();
        renderModal(onClose);

        const closeButton = container?.querySelector<HTMLButtonElement>('.auth-modal-close');
        const overlay = container?.querySelector<HTMLElement>('.auth-modal');

        act(() => {
            closeButton?.click();
            overlay?.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'Escape',
                bubbles: true,
            }));
        });

        expect(onClose).toHaveBeenCalledTimes(2);
    });

    it('opens the new Telegram Login SDK with the server nonce', async () => {
        const telegramAuth = vi.fn();
        const fetchAuthConfig = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({
                gauth_available: true,
                google_login_url: '/login/google',
                telegram_available: true,
                telegram_client_id: '8123456789',
                telegram_nonce: 'server-nonce',
            }),
        });
        vi.stubGlobal('Telegram', { Login: { auth: telegramAuth } });
        vi.stubGlobal('fetch', fetchAuthConfig);
        mockAuthContext.loginWithTelegram.mockResolvedValue({ success: false, error: 'telegram_auth_failed' });

        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        await act(async () => {
            root?.render(React.createElement(
                React.StrictMode,
                null,
                React.createElement(AuthModal, {
                    initialView: 'login',
                    onClose: vi.fn(),
                })
            ));
        });

        const telegramButton = container.querySelector<HTMLButtonElement>(
            'button[aria-label="authModal.actions.loginWithTelegram"]'
        );
        expect(telegramButton).not.toBeNull();
        expect(telegramButton?.disabled).toBe(false);
        expect(fetchAuthConfig).toHaveBeenCalledTimes(1);
        const googleButton = Array.from(container.querySelectorAll<HTMLAnchorElement>('a'))
            .find((element) => element.textContent?.includes('authModal.actions.loginWithGoogle'));
        expect(googleButton?.nextElementSibling).toBe(telegramButton);
        expect(googleButton?.className).toBe(telegramButton?.className);
        expect(container.textContent).not.toContain('authModal.orEmail');

        act(() => telegramButton?.click());

        expect(telegramAuth).toHaveBeenCalledWith(
            expect.objectContaining({
                client_id: 8123456789,
                scope: ['profile', 'write'],
                nonce: 'server-nonce',
            }),
            expect.any(Function)
        );
    });

    it('uses a private bot deep link in link mode', async () => {
        const fetchAuthConfig = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({
                gauth_available: false,
                telegram_bot_link_available: true,
            }),
        });
        vi.stubGlobal('fetch', fetchAuthConfig);
        mockAuthService.createTelegramLink.mockResolvedValue({
            url: 'https://t.me/remind_bot?start=connect_private-token',
            request_id: 'private-request-id',
            expires_in: 600,
        });
        mockAuthService.getTelegramLinkStatus.mockResolvedValue({ status: 'pending' });

        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        await act(async () => {
            root?.render(
                React.createElement(AuthModal, {
                    initialView: 'login',
                    authMode: 'link',
                    onClose: vi.fn(),
                })
            );
        });

        const telegramLink = container.querySelector<HTMLAnchorElement>(
            'a[aria-label="authModal.telegramLink.openTelegram"]'
        );
        expect(telegramLink).not.toBeNull();
        expect(telegramLink?.href).toBe('https://t.me/remind_bot?start=connect_private-token');
        expect(telegramLink?.target).toBe('_blank');
        expect(container.textContent).toContain('authModal.telegramLinkTitle');
        expect(container.textContent).toContain('authModal.telegramLinkDescription');
        expect(container.textContent).toContain('authModal.telegramLink.privateHint');
        expect(container.querySelector('#loginEmail')).toBeNull();
        expect(container.querySelector('#loginPassword')).toBeNull();
        expect(container.querySelector('#loginTurnstileContainer')).toBeNull();
        expect(mockAuthService.createTelegramLink).toHaveBeenCalledTimes(1);
        expect(mockAuthService.getTelegramLinkStatus).toHaveBeenCalledWith('private-request-id');
        expect(mockAuthService.linkTelegram).toHaveBeenCalledTimes(0);
        expect(mockAuthContext.loginWithTelegram).toHaveBeenCalledTimes(0);
    });
});
