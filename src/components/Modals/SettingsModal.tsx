import { useState, useEffect, useCallback, type FormEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
    Accessibility,
    ArrowUpRight,
    CheckCircle2,
    Download,
    FileText,
    Github,
    Globe2,
    Info,
    LayoutPanelLeft,
    LogOut,
    Loader2,
    MessageCircle,
    Music2,
    Palette,
    PlugZap,
    Send,
    Save,
    ShieldAlert,
    ShieldCheck,
    SlidersHorizontal,
    Youtube,
    UserRound,
    X,
} from 'lucide-react';
import { useSettings } from '../../context/SettingsContext';
import { useAuth } from '../../context/AuthContext';
import { authService } from '../../services/auth';
import { apiService, type GitHubStatus } from '../../services/api';
import { useURLRouter } from '../../hooks/useURLRouter';
import CustomSelect from '../UI/CustomSelect';
import ModalShell from '../UI/ModalShell';
import ToggleSwitch from '../UI/ToggleSwitch';
import { requestNotificationPermission } from '../../utils/notifications';
import { showToast } from '../../utils/toast';
import { cn } from '../../utils/cn';
import {
    firstAccountFieldError,
    localizeAccountError,
    type AccountFieldErrors,
    validateAccountName,
    validateUsername,
} from '../../utils/accountValidation';

type SettingsTabId = 'account' | 'appearance' | 'personalization' | 'privacy' | 'interface' | 'accessibility' | 'about';

type SettingsTabButtonProps = {
    active: boolean;
    icon: ReactNode;
    label: string;
    onClick: () => void;
};

type SettingsPaneProps = {
    children: ReactNode;
    dataPane: SettingsTabId;
    className?: string;
};

type SettingGroupProps = {
    title?: ReactNode;
    description?: ReactNode;
    children: ReactNode;
    className?: string;
};

type SettingControlGroupProps = {
    children: ReactNode;
    className?: string;
    withDivider?: boolean;
};

type SettingFieldProps = {
    label: ReactNode;
    hint?: ReactNode;
    children: ReactNode;
    className?: string;
    withDivider?: boolean;
};

type SettingToggleProps = {
    title: ReactNode;
    description: ReactNode;
    checked: boolean;
    onClick: () => void | Promise<void>;
    ariaLabel?: string;
    withDivider?: boolean;
};

type SettingsModalProps = {
    onClose: () => void;
    onOpenAuth: () => void;
};

type ProfileMessage = {
    type: 'success' | 'error';
    text: string;
} | null;

const MAC_SHORTCUT_KEY_CODES: Record<string, number> = {
    Space: 49,
    Enter: 36,
    NumpadEnter: 76,
    Escape: 53,
    Tab: 48,
    Backspace: 51,
    Delete: 117,
    ArrowLeft: 123,
    ArrowRight: 124,
    ArrowDown: 125,
    ArrowUp: 126,
    KeyA: 0,
    KeyS: 1,
    KeyD: 2,
    KeyF: 3,
    KeyH: 4,
    KeyG: 5,
    KeyZ: 6,
    KeyX: 7,
    KeyC: 8,
    KeyV: 9,
    KeyB: 11,
    KeyQ: 12,
    KeyW: 13,
    KeyE: 14,
    KeyR: 15,
    KeyY: 16,
    KeyT: 17,
    Digit1: 18,
    Digit2: 19,
    Digit3: 20,
    Digit4: 21,
    Digit6: 22,
    Digit5: 23,
    Equal: 24,
    Digit9: 25,
    Digit7: 26,
    Minus: 27,
    Digit8: 28,
    Digit0: 29,
    BracketRight: 30,
    KeyO: 31,
    KeyU: 32,
    BracketLeft: 33,
    KeyI: 34,
    KeyP: 35,
    KeyL: 37,
    KeyJ: 38,
    Quote: 39,
    KeyK: 40,
    Semicolon: 41,
    Backslash: 42,
    Comma: 43,
    Slash: 44,
    KeyN: 45,
    KeyM: 46,
    Period: 47,
    Backquote: 50,
    F1: 122,
    F2: 120,
    F3: 99,
    F4: 118,
    F5: 96,
    F6: 97,
    F7: 98,
    F8: 100,
    F9: 101,
    F10: 109,
    F11: 103,
    F12: 111
};

const shortcutDisplayFromRaw = (raw: string): string => {
    if (raw?.startsWith('custom:')) {
        return raw.split(':').slice(3).join(':') || raw;
    }

    return {
        optionCommandSpace: '⌥⌘Space',
        controlCommandSpace: '⌃⌘Space',
        shiftCommandSpace: '⇧⌘Space',
        commandReturn: '⌘Return'
    }[raw] || raw;
};

const keyLabelFromEvent = (event: KeyboardEvent): string => {
    if (event.code === 'Space') return 'Space';
    if (event.code === 'Enter' || event.code === 'NumpadEnter') return 'Return';
    if (event.code.startsWith('Key')) return event.code.slice(3).toUpperCase();
    if (event.code.startsWith('Digit')) return event.code.slice(5);
    if (event.code.startsWith('Numpad')) return event.code.replace('Numpad', 'Num ');
    if (event.code.startsWith('Arrow')) return event.code.replace('Arrow', '');
    return event.key && event.key.length === 1 ? event.key.toUpperCase() : event.key;
};

const shortcutRawFromEvent = (event: KeyboardEvent): string | null => {
    const keyCode = MAC_SHORTCUT_KEY_CODES[event.code];
    const modifiers = [
        event.metaKey ? 'cmd' : '',
        event.altKey ? 'option' : '',
        event.ctrlKey ? 'control' : '',
        event.shiftKey ? 'shift' : ''
    ].filter(Boolean);

    if (keyCode === undefined || modifiers.length === 0) {
        return null;
    }

    const modifierLabel = [
        event.ctrlKey ? '⌃' : '',
        event.altKey ? '⌥' : '',
        event.shiftKey ? '⇧' : '',
        event.metaKey ? '⌘' : ''
    ].join('');

    return `custom:${keyCode}:${modifiers.join(',')}:${modifierLabel}${keyLabelFromEvent(event)}`;
};

const ABOUT_LINKS = {
    website: 'https://synvexai.com/',
    policies: 'https://synvexai.com/policies/privacy-policy/',
    socials: [
        { key: 'synvexTelegram', href: 'https://t.me/SynvexAI', icon: Send },
        { key: 'youtube', href: 'https://www.youtube.com/@ReMindAi', icon: Youtube },
        { key: 'x', href: 'https://x.com/ReMindNET', icon: X },
        { key: 'telegramChannel', href: 'https://t.me/ReMindAI', icon: MessageCircle },
        { key: 'tiktok', href: 'https://www.tiktok.com/@remindai', icon: Music2 },
        { key: 'reddit', href: 'https://www.reddit.com/user/Weekly_Beginning6696/', icon: MessageCircle }
    ]
} as const;

const SettingsTabButton = ({ active, icon, label, onClick }: SettingsTabButtonProps) => (
    <button
        type="button"
        className={cn(
            'settings-tab',
            active && 'active'
        )}
        onClick={onClick}
        role="tab"
        aria-selected={active}
    >
        <span className="settings-tab-icon" aria-hidden="true">
            {icon}
        </span>
        <span className="settings-tab-label">{label}</span>
    </button>
);

const SettingsPane = ({ children, dataPane, className = '' }: SettingsPaneProps) => (
    <div
        className={cn(
            'settings-pane active ui-scrollbar-thin',
            className
        )}
        data-pane={dataPane}
        role="tabpanel"
    >
        {children}
    </div>
);

const SettingGroup = ({ title, description, children, className = '' }: SettingGroupProps) => (
    <section className={cn('setting-group', className)}>
        {title && (
            <h4 className="setting-group-title">
                {title}
            </h4>
        )}
        {description && (
            <p className="setting-group-description">
                {description}
            </p>
        )}
        {children}
    </section>
);

const SettingControlGroup = ({ children, className = '', withDivider = false }: SettingControlGroupProps) => (
    <div
        className={cn(
            'setting-control-group',
            withDivider && 'with-divider',
            className
        )}
    >
        {children}
    </div>
);

const SettingField = ({ label, hint, children, className = '', withDivider = false }: SettingFieldProps) => (
    <div className={cn('setting-field', withDivider && 'with-divider', className)}>
        <label className="setting-field-label ui-field-label">{label}</label>
        {children}
        {hint && <span className="setting-field-hint">{hint}</span>}
    </div>
);

const SettingToggle = ({ title, description, checked, onClick, ariaLabel, withDivider = false }: SettingToggleProps) => (
    <div className={cn('setting-toggle', withDivider && 'with-divider')}>
        <div className="setting-toggle-label">
            <div className="setting-toggle-title">
                {title}
            </div>
            <p className="setting-toggle-description">
                {description}
            </p>
        </div>
        <ToggleSwitch checked={checked} onClick={onClick} ariaLabel={ariaLabel || title} />
    </div>
);

const SettingsModal = ({ onClose, onOpenAuth }: SettingsModalProps) => {
    const { t, i18n } = useTranslation();
    const { settings, updateSetting } = useSettings();
    const { user, isAuthenticated, logout, updateProfile, deleteAccount } = useAuth();
    const { getSettingsTab, navigateToSettings } = useURLRouter();

    const FONT_SIZE_MIN_PX = 10;
    const FONT_SIZE_MAX_PX = 24;
    const FONT_SIZE_STEP_PX = 2;
    const settingsInputClass = 'settings-input ui-input min-h-11 rounded-md bg-surface-alt px-4 py-3 text-[0.95rem]';
    const isMacWrapper = Boolean(window.webkit?.messageHandlers?.remindMacBridge);

    const normalizeLanguage = (value) => {
        const candidate = String(value || '').toLowerCase();
        const supported = ['ru', 'en', 'zh', 'es', 'ar', 'hi', 'fr', 'bn', 'pt'];
        const match = supported.find((lng) => candidate === lng || candidate.startsWith(`${lng}-`));
        return match || 'en';
    };
    const currentLanguage = normalizeLanguage(i18n.resolvedLanguage || i18n.language || 'en');

    useEffect(() => {
        const saved = settings.interface_language;
        if (saved && saved !== currentLanguage) {
            i18n.changeLanguage(saved);
        }
    }, [currentLanguage, i18n, settings.interface_language]);

    const [activeTab, setActiveTab] = useState(() => {
        const tab = getSettingsTab();
        return tab || 'appearance';
    });
    const [name, setName] = useState('');
    const [username, setUsername] = useState('');
    const [isSavingProfile, setIsSavingProfile] = useState(false);
    const [isDeletingAccount, setIsDeletingAccount] = useState(false);
    const [isExportingData, setIsExportingData] = useState(false);
    const [githubStatus, setGithubStatus] = useState<GitHubStatus | null>(null);
    const [isLoadingGitHubStatus, setIsLoadingGitHubStatus] = useState(false);
    const [githubStatusError, setGithubStatusError] = useState('');
    const [deleteConfirmation, setDeleteConfirmation] = useState('');
    const [fieldErrors, setFieldErrors] = useState<AccountFieldErrors>({});
    const [profileMessage, setProfileMessage] = useState<ProfileMessage>(null);
    const [isRecordingShortcut, setIsRecordingShortcut] = useState(false);

    useEffect(() => {
        setName(user?.name || '');
        setUsername(user?.username || '');
        setFieldErrors({});
        setDeleteConfirmation('');
    }, [user]);

    useEffect(() => {
        const handleHashChange = () => {
            const tab = getSettingsTab();
            if (tab) {
                setActiveTab(tab);
            }
        };

        window.addEventListener('hashRouteChange', handleHashChange);
        return () => window.removeEventListener('hashRouteChange', handleHashChange);
    }, [getSettingsTab]);

    useEffect(() => {
        const handleEscapeKey = (e) => {
            if (isRecordingShortcut) {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    setIsRecordingShortcut(false);
                }
                return;
            }

            if (e.key === 'Escape') {
                onClose();
            }
        };

        document.addEventListener('keydown', handleEscapeKey);
        return () => document.removeEventListener('keydown', handleEscapeKey);
    }, [isRecordingShortcut, onClose]);

    useEffect(() => {
        if (!isRecordingShortcut) return undefined;

        const handleShortcutKeyDown = (event: KeyboardEvent) => {
            event.preventDefault();
            event.stopPropagation();

            if (event.key === 'Escape') {
                setIsRecordingShortcut(false);
                return;
            }

            if (event.key === 'Meta' || event.key === 'Alt' || event.key === 'Control' || event.key === 'Shift') {
                return;
            }

            const shortcut = shortcutRawFromEvent(event);
            if (!shortcut) {
                showToast(t('settings.interface.chatPanel.shortcut.invalid'), { type: 'warning' });
                return;
            }

            updateSetting('chatPanelKeyboardShortcut', shortcut);
            setIsRecordingShortcut(false);
        };

        window.addEventListener('keydown', handleShortcutKeyDown, true);
        return () => window.removeEventListener('keydown', handleShortcutKeyDown, true);
    }, [isRecordingShortcut, t, updateSetting]);

    useEffect(() => {
        if (!isAuthenticated && activeTab === 'personalization') {
            setActiveTab('appearance');
        }
    }, [activeTab, isAuthenticated]);

    const loadGitHubStatus = useCallback(async () => {
        if (!isAuthenticated) {
            setGithubStatus(null);
            setGithubStatusError('');
            return;
        }

        setIsLoadingGitHubStatus(true);
        setGithubStatusError('');
        try {
            const status = await apiService.getGitHubStatus();
            setGithubStatus(status);
        } catch (err) {
            const message = err instanceof Error ? err.message : t('settings.account.connectedApps.github.error');
            setGithubStatusError(message);
            setGithubStatus(null);
        } finally {
            setIsLoadingGitHubStatus(false);
        }
    }, [isAuthenticated, t]);

    useEffect(() => {
        if (activeTab === 'account' && isAuthenticated) {
            void loadGitHubStatus();
        }
    }, [activeTab, isAuthenticated, loadGitHubStatus]);

    const handleTabChange = (tab: SettingsTabId) => {
        setActiveTab(tab);
        navigateToSettings(tab, true);
    };

    const handleSaveProfile = async (e: FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        if (!isAuthenticated) return;

        setIsSavingProfile(true);
        setProfileMessage(null);
        setFieldErrors({});

        const nextFieldErrors: AccountFieldErrors = {};
        const nameError = validateAccountName(name, t);
        const usernameError = validateUsername(username, t);

        if (nameError) {
            nextFieldErrors.name = nameError;
        }
        if (usernameError) {
            nextFieldErrors.username = usernameError;
        }

        const firstError = firstAccountFieldError(nextFieldErrors);
        if (firstError) {
            setFieldErrors(nextFieldErrors);
            setProfileMessage({ type: 'error', text: firstError });
            setIsSavingProfile(false);
            return;
        }

        try {
            const res = await updateProfile({ name: name.trim(), username: username.trim() });
            if (res.success === false) {
                const localizedError = localizeAccountError(res.error, res.field, t);
                setFieldErrors(localizedError.fieldErrors);
                setProfileMessage({ type: 'error', text: localizedError.message || t('settings.account.updateError') });
                return;
            }

            setFieldErrors({});
            setProfileMessage({ type: 'success', text: t('settings.account.profileUpdated') });
        } catch (err) {
            const message = err instanceof Error ? err.message : t('settings.account.updateError');
            setProfileMessage({ type: 'error', text: message });
        } finally {
            setIsSavingProfile(false);
        }
    };

    const handleDeleteAccount = async () => {
        if (!isAuthenticated || !user?.username) return;

        if (deleteConfirmation.trim() !== user.username) {
            setProfileMessage({
                type: 'error',
                text: t('settings.account.delete.confirmationMismatch', { username: user.username })
            });
            return;
        }

        setIsDeletingAccount(true);
        setProfileMessage(null);

        try {
            const res = await deleteAccount();
            if (res.success) {
                showToast(t('settings.account.delete.success'), { type: 'success' });
                onClose();
                window.location.assign('/');
                return;
            }

            if (res.success === false) {
                setProfileMessage({
                    type: 'error',
                    text: res.error || t('settings.account.delete.error')
                });
                return;
            }

            setProfileMessage({
                type: 'error',
                text: t('settings.account.delete.error')
            });
        } catch (err) {
            const message = err instanceof Error ? err.message : t('settings.account.delete.error');
            setProfileMessage({ type: 'error', text: message });
        } finally {
            setIsDeletingAccount(false);
        }
    };

    const handleExportData = async () => {
        if (!isAuthenticated) return;

        setIsExportingData(true);
        setProfileMessage(null);

        try {
            const res = await authService.exportUserData();
            if (res.success === false) {
                setProfileMessage({ type: 'error', text: res.error || t('settings.privacy.exportError') });
                return;
            }

            const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `synvexai-data-export-${new Date().toISOString().slice(0, 10)}.json`;
            link.click();
            URL.revokeObjectURL(url);
            showToast(t('settings.privacy.exportSuccess'), { type: 'success' });
        } catch (err) {
            const message = err instanceof Error ? err.message : t('settings.privacy.exportError');
            setProfileMessage({ type: 'error', text: message });
        } finally {
            setIsExportingData(false);
        }
    };

    const parsedFontSizePx = Number.parseInt(String(settings.fontSize || ''), 10);
    const currentFontSizePx = Number.isFinite(parsedFontSizePx)
        ? Math.min(FONT_SIZE_MAX_PX, Math.max(FONT_SIZE_MIN_PX, parsedFontSizePx))
        : 16;
    const fontSizePercent = ((currentFontSizePx - FONT_SIZE_MIN_PX) / (FONT_SIZE_MAX_PX - FONT_SIZE_MIN_PX)) * 100;

    const optionalPersonalizationTabs: Array<{ id: SettingsTabId; label: string; icon: ReactNode }> = isAuthenticated
        ? [{
            id: 'personalization',
            label: t('settings.tabs.personalization'),
            icon: <SlidersHorizontal size={18} strokeWidth={1.9} />
        }]
        : [];

    const tabs: Array<{ id: SettingsTabId; label: string; icon: ReactNode }> = [
        {
            id: 'account',
            label: t('settings.tabs.account'),
            icon: <UserRound size={18} strokeWidth={1.9} />
        },
        {
            id: 'appearance',
            label: t('settings.tabs.appearance'),
            icon: <Palette size={18} strokeWidth={1.9} />
        },
        ...optionalPersonalizationTabs,
        {
            id: 'privacy',
            label: t('settings.tabs.privacy'),
            icon: <ShieldCheck size={18} strokeWidth={1.9} />
        },
        {
            id: 'interface',
            label: t('settings.tabs.interface'),
            icon: <LayoutPanelLeft size={18} strokeWidth={1.9} />
        },
        {
            id: 'accessibility',
            label: t('settings.tabs.accessibility'),
            icon: <Accessibility size={18} strokeWidth={1.9} />
        },
        {
            id: 'about',
            label: t('settings.tabs.about'),
            icon: <Info size={18} strokeWidth={1.9} />
        }
    ];

    const normalizedAccountName = String(user?.name || '').trim();
    const accountDisplayName =
        normalizedAccountName || user?.username || user?.email || t('settings.account.status.guest');
    const accountInitial = String(accountDisplayName || '?').trim().charAt(0).toUpperCase() || '?';
    const githubInstallations = githubStatus?.installations || [];
    const isGitHubConfigured = githubStatus?.configured ?? !githubStatusError;
    const isGitHubConnected = githubInstallations.length > 0;
    const githubConnectionError = githubStatusError || githubStatus?.connection_error || '';
    const githubRepositoryCount = githubStatus?.repositories?.length || 0;
    const githubStatusLabel = isLoadingGitHubStatus
        ? t('settings.account.connectedApps.github.status.checking')
        : !isGitHubConfigured
            ? t('settings.account.connectedApps.github.status.configMissing')
            : isGitHubConnected
                ? t('settings.account.connectedApps.github.status.connected')
                : t('settings.account.connectedApps.github.status.disconnected');
    const githubStatusClass = isLoadingGitHubStatus
        ? 'is-loading'
        : !isGitHubConfigured || githubConnectionError
            ? 'is-error'
            : isGitHubConnected
                ? 'is-connected'
                : 'is-disconnected';

    const handleGitHubConnect = () => {
        if (isGitHubConnected) {
            onClose();
            window.history.pushState({}, '', '/github');
            window.dispatchEvent(new PopStateEvent('popstate'));
            return;
        }
        const connectUrl = githubStatus?.urls?.connect || '/auth/github/login?after=install';
        window.location.assign(connectUrl);
    };

    const renderConnectedAppsCard = () => (
        <section className="account-card account-connected-apps-card">
            <div className="account-card-head">
                <h5 className="account-card-title">
                    {t('settings.account.connectedApps.title')}
                </h5>
                <p className="account-card-copy">
                    {t('settings.account.connectedApps.description')}
                </p>
            </div>

            <div className="account-connected-app-row">
                <span className="account-connected-app-icon" aria-hidden="true">
                    <Github size={21} strokeWidth={1.9} />
                </span>
                <div className="account-connected-app-copy">
                    <strong>{t('settings.account.connectedApps.github.name')}</strong>
                    <p>{t('settings.account.connectedApps.github.description')}</p>
                    {isGitHubConnected && githubRepositoryCount > 0 && (
                        <span className="account-connected-app-meta">
                            {t('settings.account.connectedApps.github.repoCount', {
                                count: githubRepositoryCount
                            })}
                        </span>
                    )}
                    {githubConnectionError && (
                        <span className="account-connected-app-error">
                            {githubConnectionError}
                        </span>
                    )}
                </div>
                <div className="account-connected-app-controls">
                    <span className={cn('account-connected-app-status', githubStatusClass)}>
                        {isLoadingGitHubStatus ? (
                            <Loader2 size={14} strokeWidth={2} className="animate-spin" />
                        ) : isGitHubConnected ? (
                            <CheckCircle2 size={14} strokeWidth={2} />
                        ) : null}
                        {githubStatusLabel}
                    </span>
                    <button
                        type="button"
                        className="account-connected-app-action ui-button-secondary min-h-10 rounded-md px-3 py-2"
                        onClick={handleGitHubConnect}
                        disabled={isLoadingGitHubStatus || !isGitHubConfigured}
                    >
                        <PlugZap size={15} strokeWidth={1.9} />
                        {isGitHubConnected
                            ? t('settings.account.connectedApps.github.manage')
                            : t('settings.account.connectedApps.github.connect')}
                    </button>
                </div>
            </div>
        </section>
    );

    const renderAccountTab = () => (
        <SettingsPane dataPane="account" className="account-pane">
            <div className="account-shell">
                {profileMessage && (
                    <p
                        className={cn(
                            'account-message is-visible',
                            profileMessage.type === 'success' ? 'success' : 'error'
                        )}
                    >
                        {profileMessage.text}
                    </p>
                )}

                {!isAuthenticated ? (
                    <div className="account-layout account-layout-guest">
                        <section className="account-card account-card-accent">
                            <div className="account-card-head">
                                <h5 className="account-card-title">{t('settings.account.ctaTitle')}</h5>
                                <p className="account-card-copy">{t('settings.account.ctaDescription')}</p>
                            </div>
                            <div className="account-actions">
                                <button
                                    type="button"
                                    className="btn-primary ui-button-primary min-h-11 rounded-md px-5 py-3"
                                    onClick={() => { onClose(); onOpenAuth(); }}
                                >
                                    {t('settings.account.signInOrRegister')}
                                </button>
                            </div>
                        </section>

                        <section className="account-card account-card-muted">
                            <div className="account-card-head">
                                <h5 className="account-card-title">{t('settings.account.guestMode')}</h5>
                                <p className="account-card-copy">{t('settings.account.ctaDescription')}</p>
                            </div>
                        </section>
                    </div>
                ) : (
                    <>
                    <section className="account-profile-summary">
                        <div className="account-avatar" aria-hidden="true">
                            {accountInitial}
                        </div>
                        <div className="account-profile-copy">
                            <h5 className="account-profile-name">{accountDisplayName}</h5>
                            <p className="account-profile-meta">
                                @{user?.username || t('settings.account.unavailable')}
                            </p>
                        </div>
                        <button
                            type="button"
                            className="account-signout-btn ui-button-secondary min-h-10 rounded-md px-3 py-2"
                            onClick={logout}
                        >
                            <LogOut size={16} strokeWidth={1.9} />
                            {t('settings.account.signOut')}
                        </button>
                    </section>

                    <div className="account-layout account-layout-auth">
                        <form className="account-card account-form-card" onSubmit={handleSaveProfile}>
                            <div className="account-card-head">
                                <h5 className="account-card-title">{t('settings.account.saveChanges')}</h5>
                                <p className="account-card-copy">{t('settings.account.description')}</p>
                            </div>

                            <div className="account-form-grid">
                                <SettingField
                                    label={t('settings.account.fields.name')}
                                    hint={t('settings.account.nameHint')}
                                    className="account-field"
                                >
                                    <input
                                        className={settingsInputClass}
                                        type="text"
                                        id="accountNameInput"
                                        aria-label={t('settings.account.fields.name')}
                                        value={name}
                                        onChange={(e) => {
                                            setName(e.target.value);
                                            setFieldErrors((prev) => ({ ...prev, name: undefined }));
                                        }}
                                        maxLength={100}
                                    />
                                    {fieldErrors.name && (
                                        <span className="text-xs leading-5 text-danger">{fieldErrors.name}</span>
                                    )}
                                </SettingField>

                                <SettingField
                                    label={t('settings.account.fields.username')}
                                    hint={t('settings.account.usernameHint')}
                                    className="account-field"
                                >
                                    <input
                                        className={settingsInputClass}
                                        type="text"
                                        id="accountUsernameInput"
                                        aria-label={t('settings.account.fields.username')}
                                        value={username}
                                        onChange={(e) => {
                                            setUsername(e.target.value);
                                            setFieldErrors((prev) => ({ ...prev, username: undefined }));
                                        }}
                                        maxLength={50}
                                        required
                                    />
                                    {fieldErrors.username && (
                                        <span className="text-xs leading-5 text-danger">{fieldErrors.username}</span>
                                    )}
                                </SettingField>

                                <SettingField
                                    label={t('settings.account.fields.email')}
                                    hint={t('settings.account.emailReadonlyHint')}
                                    className="account-field account-field-full"
                                >
                                    <input
                                        className={cn(settingsInputClass, 'cursor-not-allowed opacity-75')}
                                        type="email"
                                        id="accountEmailInput"
                                        aria-label={t('settings.account.fields.email')}
                                        value={user?.email || ''}
                                        disabled
                                    />
                                </SettingField>
                            </div>

                            <div className="account-actions">
                                <button
                                    type="submit"
                                    className="btn-primary account-save-btn ui-button-primary min-h-11 rounded-md px-5 py-3"
                                    disabled={isSavingProfile}
                                >
                                    <Save size={16} strokeWidth={1.9} />
                                    {isSavingProfile ? t('settings.account.saving') : t('settings.account.saveChanges')}
                                </button>
                            </div>
                        </form>

                        {renderConnectedAppsCard()}
                    </div>

                    <section className="account-card account-danger-card">
                        <div className="account-card-head account-danger-head">
                            <h5 className="account-card-title account-danger-title">
                                <ShieldAlert size={17} strokeWidth={1.9} />
                                {t('settings.account.delete.title')}
                            </h5>
                            <p className="account-card-copy">{t('settings.account.delete.description')}</p>
                        </div>
                        <div className="account-danger-controls">
                            <SettingField
                                label={t('settings.account.delete.confirmLabel')}
                                className="account-field"
                            >
                                <input
                                    className={settingsInputClass}
                                    type="text"
                                    id="accountDeleteConfirmationInput"
                                    aria-label={t('settings.account.delete.confirmLabel')}
                                    value={deleteConfirmation}
                                    onChange={(e) => setDeleteConfirmation(e.target.value)}
                                    placeholder={t('settings.account.delete.confirmPlaceholder')}
                                />
                            </SettingField>
                            <button
                                type="button"
                                className="account-delete-btn ui-button-secondary min-h-11 rounded-md px-4 py-3"
                                onClick={handleDeleteAccount}
                                disabled={isDeletingAccount}
                            >
                                {isDeletingAccount
                                    ? t('settings.account.delete.actionLoading')
                                    : t('settings.account.delete.action')}
                            </button>
                        </div>
                    </section>
                    </>
                )}
            </div>
        </SettingsPane>
    );

    return (
        <ModalShell
            ariaLabel={t('settings.title')}
            className="user-settings-modal active items-end px-0 py-0 sm:items-center sm:px-4 sm:py-6"
            contentClassName="user-settings-content flex h-[100dvh] min-h-[100dvh] w-full max-w-[1000px] flex-col rounded-none border-border bg-surface shadow-[var(--shadow-xl)] sm:h-[85vh] sm:min-h-[560px] sm:rounded-xl"
            onBackdropClick={onClose}
            onRequestClose={onClose}
        >
            <div className="user-settings-header flex items-center justify-between border-b border-border px-4 py-3 sm:px-5">
                <h3 className="text-[1.05rem] font-semibold tracking-normal text-foreground">
                    {t('settings.title')}
                </h3>
                <button
                    className="user-settings-close ui-icon-control size-9 rounded-md border-transparent bg-transparent text-muted hover:bg-interactive hover:text-foreground"
                    onClick={onClose}
                    aria-label={t('settings.close')}
                    type="button"
                >
                    <X size={20} strokeWidth={1.9} />
                </button>
            </div>

            <div className="user-settings-body flex min-h-0 flex-1 flex-col overflow-hidden md:flex-row">
                <div className="settings-tabs ui-scrollbar-thin" role="tablist" aria-label={t('settings.title')}>
                    {tabs.map((tab) => (
                        <SettingsTabButton
                            key={tab.id}
                            active={activeTab === tab.id}
                            icon={tab.icon}
                            label={tab.label}
                            onClick={() => handleTabChange(tab.id)}
                        />
                    ))}
                </div>

                <div className="settings-content">
                    {activeTab === 'account' && renderAccountTab()}

                    {activeTab === 'appearance' && (
                        <SettingsPane dataPane="appearance" className="settings-pane-standard">
                            <SettingGroup title={t('settings.appearance.themeGroup')}>
                                <SettingControlGroup className="items-start">
                                    <CustomSelect
                                        label={t('settings.appearance.themeLabel')}
                                        value={settings.theme}
                                        onChange={(value) => updateSetting('theme', value)}
                                        options={[
                                            { value: 'system', label: t('settings.appearance.theme.system') },
                                            { value: 'dark', label: t('settings.appearance.theme.dark') },
                                            { value: 'light', label: t('settings.appearance.theme.light') }
                                        ]}
                                    />
                                </SettingControlGroup>
                                <SettingControlGroup className="items-start" withDivider>
                                    <CustomSelect
                                        label={t('settings.appearance.accentLabel')}
                                        value={settings.accentColor}
                                        onChange={(value) => updateSetting('accentColor', value)}
                                        options={[
                                            { value: 'white', label: t('settings.appearance.accent.white') },
                                            { value: 'blue', label: t('settings.appearance.accent.blue') },
                                            { value: 'green', label: t('settings.appearance.accent.green') },
                                            { value: 'yellow', label: t('settings.appearance.accent.yellow') },
                                            { value: 'pink', label: t('settings.appearance.accent.pink') },
                                            { value: 'orange', label: t('settings.appearance.accent.orange') },
                                            { value: 'black', label: t('settings.appearance.accent.black') },
                                            { value: 'purple', label: t('settings.appearance.accent.purple') },
                                            { value: 'cyan', label: t('settings.appearance.accent.cyan') }
                                        ]}
                                    />
                                </SettingControlGroup>
                            </SettingGroup>

                            <SettingGroup title={t('settings.appearance.contentGroup')}>
                                <SettingToggle
                                    title={t('settings.appearance.renderMarkdown.title')}
                                    description={t('settings.appearance.renderMarkdown.description')}
                                    checked={settings.renderMarkdown}
                                    onClick={() => updateSetting('renderMarkdown', !settings.renderMarkdown)}
                                />
                                <SettingToggle
                                    title={t('settings.appearance.snowBackground.title')}
                                    description={t('settings.appearance.snowBackground.description')}
                                    checked={settings.snowBackground}
                                    onClick={() => updateSetting('snowBackground', !settings.snowBackground)}
                                    withDivider
                                />
                                <SettingToggle
                                    title={t('settings.appearance.compactMode.title')}
                                    description={t('settings.appearance.compactMode.description')}
                                    checked={settings.compactMode}
                                    onClick={() => updateSetting('compactMode', !settings.compactMode)}
                                    withDivider
                                />
                            </SettingGroup>
                        </SettingsPane>
                    )}

                    {activeTab === 'personalization' && isAuthenticated && (
                        <SettingsPane dataPane="personalization" className="settings-pane-standard">
                            <SettingGroup
                                title={t('settings.personalization.title')}
                                description={t('settings.personalization.description')}
                            >
                                <SettingToggle
                                    title={t('settings.personalization.automaticWebSearch.title')}
                                    description={t('settings.personalization.automaticWebSearch.description')}
                                    checked={!!settings.automaticWebSearch}
                                    onClick={() => updateSetting('automaticWebSearch', !settings.automaticWebSearch)}
                                />
                                <SettingField label={t('settings.personalization.instructionsLabel')} withDivider>
                                    <textarea
                                        className={cn(settingsInputClass, 'min-h-32 resize-y')}
                                        rows={5}
                                        aria-label={t('settings.personalization.instructionsLabel')}
                                        value={settings.personalization_instructions || ''}
                                        onChange={(e) => updateSetting('personalization_instructions', e.target.value)}
                                        placeholder={t('settings.personalization.instructionsPlaceholder')}
                                    />
                                </SettingField>
                                <SettingField label={t('settings.personalization.nicknameLabel')} withDivider>
                                    <input
                                        type="text"
                                        className={settingsInputClass}
                                        aria-label={t('settings.personalization.nicknameLabel')}
                                        value={settings.personalization_nickname || ''}
                                        onChange={(e) => updateSetting('personalization_nickname', e.target.value)}
                                    />
                                </SettingField>
                                <SettingField label={t('settings.personalization.professionLabel')} withDivider>
                                    <input
                                        type="text"
                                        className={settingsInputClass}
                                        aria-label={t('settings.personalization.professionLabel')}
                                        value={settings.personalization_profession || ''}
                                        onChange={(e) => updateSetting('personalization_profession', e.target.value)}
                                    />
                                </SettingField>
                                <SettingField label={t('settings.personalization.moreLabel')} withDivider>
                                    <textarea
                                        className={cn(settingsInputClass, 'min-h-24 resize-y')}
                                        rows={3}
                                        aria-label={t('settings.personalization.moreLabel')}
                                        value={settings.personalization_more || ''}
                                        onChange={(e) => updateSetting('personalization_more', e.target.value)}
                                        placeholder={t('settings.personalization.morePlaceholder')}
                                    />
                                </SettingField>
                            </SettingGroup>
                        </SettingsPane>
                    )}

                    {activeTab === 'privacy' && (
                        <SettingsPane dataPane="privacy" className="settings-pane-standard">
                            {profileMessage && (
                                <p
                                    className={cn(
                                        'account-message is-visible',
                                        profileMessage.type === 'success' ? 'success' : 'error'
                                    )}
                                >
                                    {profileMessage.text}
                                </p>
                            )}
                            <SettingGroup
                                title={t('settings.privacy.title')}
                                description={t('settings.privacy.description')}
                            >
                                <SettingToggle
                                    title={t('settings.privacy.serviceImprovement.title')}
                                    description={t('settings.privacy.serviceImprovement.description')}
                                    checked={!!settings.service_improvement_opt_in}
                                    onClick={() => updateSetting('service_improvement_opt_in', !settings.service_improvement_opt_in)}
                                />
                                {isAuthenticated ? (
                                    <SettingControlGroup withDivider>
                                        <button
                                            type="button"
                                            className="ui-button-secondary min-h-11 rounded-md px-4 py-3"
                                            onClick={handleExportData}
                                            disabled={isExportingData}
                                        >
                                            <Download size={16} strokeWidth={1.9} />
                                            {isExportingData
                                                ? t('settings.privacy.exportLoading')
                                                : t('settings.privacy.exportAction')}
                                        </button>
                                    </SettingControlGroup>
                                ) : (
                                    <SettingControlGroup withDivider>
                                        <button
                                            type="button"
                                            className="ui-button-secondary min-h-11 rounded-md px-4 py-3"
                                            onClick={() => { onClose(); onOpenAuth(); }}
                                        >
                                            {t('settings.privacy.signInForExport')}
                                        </button>
                                    </SettingControlGroup>
                                )}
                                <SettingControlGroup withDivider>
                                    <a
                                        className="settings-about-action-card"
                                        href={ABOUT_LINKS.policies}
                                        target="_blank"
                                        rel="noreferrer"
                                    >
                                        <span className="settings-about-action-icon" aria-hidden="true">
                                            <FileText size={20} strokeWidth={1.9} />
                                        </span>
                                        <span className="settings-about-action-copy">
                                            <span>{t('settings.privacy.policyLink.title')}</span>
                                            <small>{t('settings.privacy.policyLink.description')}</small>
                                        </span>
                                        <ArrowUpRight size={17} strokeWidth={2} aria-hidden="true" />
                                    </a>
                                </SettingControlGroup>
                            </SettingGroup>
                        </SettingsPane>
                    )}

                    {activeTab === 'interface' && (
                        <SettingsPane dataPane="interface" className="settings-pane-standard">
                            <SettingGroup title={t('settings.interfaceLanguage.title')}>
                                <SettingControlGroup className="items-start">
                                    <CustomSelect
                                        label={t('settings.interfaceLanguage.selectLabel')}
                                        value={settings.interface_language || currentLanguage}
                                        onChange={(value) => {
                                            updateSetting('interface_language', value);
                                            i18n.changeLanguage(value);
                                        }}
                                        options={[
                                            { value: 'en', label: t('settings.languages.en') },
                                            { value: 'ru', label: t('settings.languages.ru') },
                                            { value: 'zh', label: t('settings.languages.zh') },
                                            { value: 'es', label: t('settings.languages.es') },
                                            { value: 'ar', label: t('settings.languages.ar') },
                                            { value: 'hi', label: t('settings.languages.hi') },
                                            { value: 'fr', label: t('settings.languages.fr') },
                                            { value: 'bn', label: t('settings.languages.bn') },
                                            { value: 'pt', label: t('settings.languages.pt') }
                                        ]}
                                    />
                                </SettingControlGroup>
                            </SettingGroup>

                            <SettingGroup title={t('settings.interface.navigationGroup')}>
                                <SettingToggle
                                    title={t('settings.interface.showChatPreview.title')}
                                    description={t('settings.interface.showChatPreview.description')}
                                    checked={settings.showChatPreview}
                                    onClick={() => updateSetting('showChatPreview', !settings.showChatPreview)}
                                />
                                <SettingToggle
                                    title={t('settings.interface.autocomplete.title')}
                                    description={t('settings.interface.autocomplete.description')}
                                    checked={settings.autocomplete}
                                    onClick={() => updateSetting('autocomplete', !settings.autocomplete)}
                                    withDivider
                                />
                            </SettingGroup>

                            {isMacWrapper && (
                                <SettingGroup className="mac-chat-panel-group">
                                    <div className="mac-chat-panel-head">
                                        <div className="mac-chat-panel-head-copy">
                                            <h4>{t('settings.interface.chatPanel.group')}</h4>
                                            <p>{t('settings.interface.chatPanel.shortcut.record', {
                                                shortcut: shortcutDisplayFromRaw(settings.chatPanelKeyboardShortcut)
                                            })}</p>
                                        </div>
                                        <button
                                            type="button"
                                            className={cn(
                                                'mac-chat-panel-record',
                                                isRecordingShortcut && 'is-recording'
                                            )}
                                            onClick={() => setIsRecordingShortcut((recording) => !recording)}
                                        >
                                            <span>
                                                {isRecordingShortcut
                                                    ? t('settings.interface.chatPanel.shortcut.recording')
                                                    : shortcutDisplayFromRaw(settings.chatPanelKeyboardShortcut)}
                                            </span>
                                        </button>
                                    </div>

                                    <div className="mac-chat-panel-grid">
                                        <section className="mac-chat-panel-card mac-chat-panel-card-wide">
                                            <div className="mac-chat-panel-card-title">
                                                <span>{t('settings.interface.chatPanel.position.label')}</span>
                                            </div>
                                            <div className="mac-chat-panel-option-grid position-grid">
                                                {[
                                                    ['bottomCenter', t('settings.interface.chatPanel.position.bottomCenter')],
                                                    ['center', t('settings.interface.chatPanel.position.center')],
                                                    ['topCenter', t('settings.interface.chatPanel.position.topCenter')],
                                                    ['right', t('settings.interface.chatPanel.position.right')],
                                                    ['left', t('settings.interface.chatPanel.position.left')]
                                                ].map(([value, label]) => (
                                                    <button
                                                        key={value}
                                                        type="button"
                                                        className={cn(
                                                            'mac-chat-panel-option',
                                                            settings.chatPanelPosition === value && 'is-active'
                                                        )}
                                                        onClick={() => updateSetting('chatPanelPosition', value)}
                                                    >
                                                        {label}
                                                    </button>
                                                ))}
                                            </div>
                                        </section>

                                        <section className="mac-chat-panel-card">
                                            <div className="mac-chat-panel-card-title">
                                                <span>{t('settings.interface.chatPanel.reset.label')}</span>
                                            </div>
                                            <div className="mac-chat-panel-option-stack">
                                                {[
                                                    ['never', t('settings.interface.chatPanel.reset.never')],
                                                    ['after5Minutes', t('settings.interface.chatPanel.reset.after5')],
                                                    ['after10Minutes', t('settings.interface.chatPanel.reset.after10')],
                                                    ['after30Minutes', t('settings.interface.chatPanel.reset.after30')]
                                                ].map(([value, label]) => (
                                                    <button
                                                        key={value}
                                                        type="button"
                                                        className={cn(
                                                            'mac-chat-panel-option',
                                                            settings.chatPanelResetPolicy === value && 'is-active'
                                                        )}
                                                        onClick={() => updateSetting('chatPanelResetPolicy', value)}
                                                    >
                                                        {label}
                                                    </button>
                                                ))}
                                            </div>
                                        </section>

                                        <section className="mac-chat-panel-card">
                                            <div className="mac-chat-panel-card-title">
                                                <span>{t('settings.interface.chatPanel.newChat.label')}</span>
                                            </div>
                                            <div className="mac-chat-panel-option-stack">
                                                {[
                                                    ['companion', t('settings.interface.chatPanel.newChat.companion')],
                                                    ['browser', t('settings.interface.chatPanel.newChat.browser')]
                                                ].map(([value, label]) => (
                                                    <button
                                                        key={value}
                                                        type="button"
                                                        className={cn(
                                                            'mac-chat-panel-option',
                                                            settings.chatPanelNewChatDestination === value && 'is-active'
                                                        )}
                                                        onClick={() => updateSetting('chatPanelNewChatDestination', value)}
                                                    >
                                                        {label}
                                                    </button>
                                                ))}
                                            </div>
                                        </section>
                                    </div>

                                    <div
                                        role="group"
                                        className={cn(
                                            'mac-chat-panel-launch',
                                            settings.macLaunchAtLogin === true && 'is-active'
                                        )}
                                    >
                                        <span className="mac-chat-panel-launch-copy">
                                            <strong>{t('settings.interface.chatPanel.launchAtLogin.title')}</strong>
                                            <small>{t('settings.interface.chatPanel.launchAtLogin.description')}</small>
                                        </span>
                                        <ToggleSwitch
                                            checked={settings.macLaunchAtLogin === true}
                                            onClick={() => updateSetting('macLaunchAtLogin', settings.macLaunchAtLogin !== true)}
                                            ariaLabel={t('settings.interface.chatPanel.launchAtLogin.title')}
                                        />
                                    </div>
                                </SettingGroup>
                            )}

                            <SettingGroup title={t('settings.interface.behaviorGroup')}>
                                <SettingToggle
                                    title={t('settings.interface.autoscroll.title')}
                                    description={t('settings.interface.autoscroll.description')}
                                    checked={settings.autoscroll}
                                    onClick={() => updateSetting('autoscroll', !settings.autoscroll)}
                                />
                                <SettingToggle
                                    title={t('settings.interface.notifyOnThinkingDone.title')}
                                    description={t('settings.interface.notifyOnThinkingDone.description')}
                                    checked={settings.notifyOnThinkingDone}
                                    onClick={async () => {
                                        const next = !settings.notifyOnThinkingDone;
                                        updateSetting('notifyOnThinkingDone', next);
                                        if (next) {
                                            const permission = await requestNotificationPermission();
                                            if (permission !== 'granted') {
                                                showToast(t('settings.interface.notifyPermissionWarning'), { type: 'warning' });
                                            }
                                        }
                                    }}
                                    withDivider
                                />
                                <SettingToggle
                                    title={t('settings.interface.requireCtrlEnter.title')}
                                    description={t('settings.interface.requireCtrlEnter.description')}
                                    checked={settings.requireCtrlEnterToSend}
                                    onClick={() => updateSetting('requireCtrlEnterToSend', !settings.requireCtrlEnterToSend)}
                                    withDivider
                                />
                                <SettingToggle
                                    title={t('settings.interface.renderUserMarkdown.title')}
                                    description={t('settings.interface.renderUserMarkdown.description')}
                                    checked={settings.renderUserMarkdown}
                                    onClick={() => updateSetting('renderUserMarkdown', !settings.renderUserMarkdown)}
                                    withDivider
                                />
                                <SettingToggle
                                    title={t('settings.interface.autoSave.title')}
                                    description={t('settings.interface.autoSave.description')}
                                    checked={settings.autoSave}
                                    onClick={() => updateSetting('autoSave', !settings.autoSave)}
                                    withDivider
                                />
                            </SettingGroup>
                        </SettingsPane>
                    )}

                    {activeTab === 'accessibility' && (
                        <SettingsPane dataPane="accessibility" className="settings-pane-standard">
                            <SettingGroup title={t('settings.accessibility.typographyGroup')}>
                                <SettingControlGroup className="items-start">
                                    <CustomSelect
                                        label={t('settings.accessibility.fontFamilyLabel')}
                                        value={settings.fontFamily}
                                        onChange={(value) => updateSetting('fontFamily', value)}
                                        options={[
                                            { value: "'Nunito', 'SF Pro Text', 'Ubuntu', 'Segoe UI', sans-serif", label: 'Nunito' },
                                            { value: "'Inter', sans-serif", label: 'Inter' },
                                            { value: "'Manrope', sans-serif", label: 'Manrope' },
                                            { value: "'JetBrains Mono', monospace", label: 'JetBrains Mono' }
                                        ]}
                                    />
                                </SettingControlGroup>
                                <SettingControlGroup withDivider>
                                    <div className="setting-range-wrapper flex w-full flex-col gap-4 md:flex-row md:items-start md:justify-between">
                                        <div className="setting-range-label text-sm font-medium text-foreground">
                                            {t('settings.accessibility.fontSizeLabel')}
                                        </div>
                                        <div className="setting-range-control relative w-full max-w-60 pt-[18px]">
                                            <div
                                                className="setting-range-bubble absolute top-0 rounded-full border border-border-strong bg-interactive px-2 py-0.5 text-[0.78rem] font-semibold text-foreground"
                                                style={{ left: `${fontSizePercent}%`, transform: 'translateX(-50%)' }}
                                                aria-hidden="true"
                                            >
                                                {currentFontSizePx}px
                                            </div>
                                            <input
                                                className="setting-range w-full"
                                                type="range"
                                                min={FONT_SIZE_MIN_PX}
                                                max={FONT_SIZE_MAX_PX}
                                                step={FONT_SIZE_STEP_PX}
                                                value={currentFontSizePx}
                                                onChange={(e) => updateSetting('fontSize', `${e.target.value}px`)}
                                                aria-label={t('settings.accessibility.fontSizeLabel')}
                                            />
                                            <div className="setting-range-ticks mt-1 flex justify-between" aria-hidden="true">
                                                {Array.from(
                                                    { length: Math.floor((FONT_SIZE_MAX_PX - FONT_SIZE_MIN_PX) / FONT_SIZE_STEP_PX) + 1 },
                                                    (_, i) => FONT_SIZE_MIN_PX + i * FONT_SIZE_STEP_PX
                                                ).map((v) => (
                                                    <span key={v} className="setting-range-tick block h-1.5 w-px rounded-full bg-white/20" />
                                                ))}
                                            </div>
                                            <div className="setting-range-meta mt-1 flex justify-between text-[0.78rem] text-subtle">
                                                <span>{FONT_SIZE_MIN_PX}px</span>
                                                <span>{FONT_SIZE_MAX_PX}px</span>
                                            </div>
                                        </div>
                                    </div>
                                </SettingControlGroup>
                            </SettingGroup>

                            <SettingGroup title={t('settings.accessibility.accessibilityGroup')}>
                                <SettingToggle
                                    title={t('settings.accessibility.keyboardSupport.title')}
                                    description={t('settings.accessibility.keyboardSupport.description')}
                                    checked={settings.keyboardSupport}
                                    onClick={() => updateSetting('keyboardSupport', !settings.keyboardSupport)}
                                />
                                <SettingToggle
                                    title={t('settings.accessibility.highContrast.title')}
                                    description={t('settings.accessibility.highContrast.description')}
                                    checked={settings.highContrast}
                                    onClick={() => updateSetting('highContrast', !settings.highContrast)}
                                    withDivider
                                />
                            </SettingGroup>

                            <SettingGroup title={t('settings.accessibility.codeGroup')}>
                                <SettingToggle
                                    title={t('settings.accessibility.codeWrap.title')}
                                    description={t('settings.accessibility.codeWrap.description')}
                                    checked={settings.codeWrap}
                                    onClick={() => updateSetting('codeWrap', !settings.codeWrap)}
                                />
                            </SettingGroup>
                        </SettingsPane>
                    )}

                    {activeTab === 'about' && (
                        <SettingsPane dataPane="about" className="settings-pane-standard settings-about-pane">
                            <div className="settings-about-action-grid" aria-label={t('settings.about.quickLinksLabel')}>
                                <a
                                    className="settings-about-action-card"
                                    href={ABOUT_LINKS.website}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    <span className="settings-about-action-icon" aria-hidden="true">
                                        <Globe2 size={20} strokeWidth={1.9} />
                                    </span>
                                    <span className="settings-about-action-copy">
                                        <span>{t('settings.about.website.title')}</span>
                                        <small>{t('settings.about.website.description')}</small>
                                    </span>
                                    <ArrowUpRight size={17} strokeWidth={2} aria-hidden="true" />
                                </a>

                                <a
                                    className="settings-about-action-card"
                                    href={ABOUT_LINKS.policies}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    <span className="settings-about-action-icon" aria-hidden="true">
                                        <FileText size={20} strokeWidth={1.9} />
                                    </span>
                                    <span className="settings-about-action-copy">
                                        <span>{t('settings.about.policies.title')}</span>
                                        <small>{t('settings.about.policies.description')}</small>
                                    </span>
                                    <ArrowUpRight size={17} strokeWidth={2} aria-hidden="true" />
                                </a>
                            </div>

                            <section className="settings-about-section">
                                <div className="settings-about-section-head">
                                    <h4>{t('settings.about.socials.title')}</h4>
                                    <p>{t('settings.about.socials.description')}</p>
                                </div>
                                <div className="settings-social-grid">
                                    {ABOUT_LINKS.socials.map((link) => {
                                        const SocialIcon = link.icon;

                                        return (
                                            <a
                                                key={link.key}
                                                className="settings-social-card"
                                                href={link.href}
                                                target="_blank"
                                                rel="noreferrer"
                                            >
                                                <span className="settings-social-icon" aria-hidden="true">
                                                    <SocialIcon size={19} strokeWidth={1.9} />
                                                </span>
                                                <span className="settings-social-copy">
                                                    <span>{t(`settings.about.socials.links.${link.key}`)}</span>
                                                    <small>{link.href.replace(/^https?:\/\//, '')}</small>
                                                </span>
                                                <ArrowUpRight size={15} strokeWidth={2} aria-hidden="true" />
                                            </a>
                                        );
                                    })}
                                </div>
                            </section>
                        </SettingsPane>
                    )}
                </div>
            </div>
        </ModalShell>
    );
};

export default SettingsModal;
