import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AuthModal from './AuthModal';

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string) => key,
    }),
}));

vi.mock('../../context/AuthContext', () => ({
    useAuth: () => ({
        login: vi.fn(),
    }),
}));

vi.mock('../../services/auth', () => ({
    authService: {
        register: vi.fn(),
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
        container = null;
        root = null;
    });

    function renderModal(onClose: () => void) {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(AuthModal, {
                initialView: 'register',
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
});
