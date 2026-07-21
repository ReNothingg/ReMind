import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AppRail from './AppRail';

vi.mock('../../context/AuthContext', () => ({
    useAuth: () => ({ isAuthenticated: false, user: { is_admin: true } }),
}));

vi.mock('../../context/SettingsContext', () => ({
    useSettings: () => ({ settings: { showChatPreview: true } }),
}));

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}));

describe('AppRail pinned minds section', () => {
    let container: HTMLDivElement | null = null;
    let root: Root | null = null;

    afterEach(() => {
        if (root) {
            act(() => root?.unmount());
        }
        container?.remove();
        root = null;
        container = null;
    });

    it('renders pinned minds below Minds and lets the user collapse them', () => {
        container = document.createElement('div');
        document.body.appendChild(container);
        root = createRoot(container);

        act(() => {
            root?.render(React.createElement(AppRail, {
                activeMindId: null,
                currentPath: '/',
                currentSessionId: null,
                isExpanded: true,
                onAdminClick: vi.fn(),
                onMindsClick: vi.fn(),
                onNewChat: vi.fn(),
                onSelectMind: vi.fn(),
                onSelectSession: vi.fn(),
                onSessionDeleted: vi.fn(),
                onSessionRenamed: vi.fn(),
                onSettingsClick: vi.fn(),
                onToggle: vi.fn(),
                pinnedMinds: [{ public_id: 'mind-1', name: 'Pinned mind' }],
                sessions: [],
            }));
        });

        const mindsButton = container.querySelector('#railMinds');
        const pinnedButton = container.querySelector<HTMLButtonElement>('.ui-rail-pinned-mind');
        const adminButton = container.querySelector('#railAdmin');
        const toggle = container.querySelector<HTMLButtonElement>('.ui-rail-pinned-minds-toggle');
        const disclosure = container.querySelector('.ui-rail-pinned-minds-disclosure');

        expect(mindsButton?.compareDocumentPosition(pinnedButton as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(pinnedButton?.compareDocumentPosition(adminButton as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(toggle?.getAttribute('aria-expanded')).toBe('true');

        act(() => toggle?.click());

        expect(toggle?.getAttribute('aria-expanded')).toBe('false');
        expect(disclosure?.getAttribute('aria-hidden')).toBe('true');
        expect(disclosure?.hasAttribute('inert')).toBe(true);
        expect(container.querySelector('.ui-rail-pinned-mind')).not.toBeNull();

        act(() => toggle?.click());

        expect(toggle?.getAttribute('aria-expanded')).toBe('true');
        expect(disclosure?.getAttribute('aria-hidden')).toBe('false');
        expect(disclosure?.hasAttribute('inert')).toBe(false);
        expect(container.querySelector('.ui-rail-pinned-mind')).not.toBeNull();
    });
});
