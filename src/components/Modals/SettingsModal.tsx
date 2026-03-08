import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useSettings } from '../../context/SettingsContext';
import { useAuth } from '../../context/AuthContext';
import { useURLRouter } from '../../hooks/useURLRouter';
import CustomSelect from '../UI/CustomSelect';
import ModalShell from '../UI/ModalShell';
import ToggleSwitch from '../UI/ToggleSwitch';
import { requestNotificationPermission } from '../../utils/notifications';
import { showToast } from '../../utils/toast';
import { cn } from '../../utils/cn';

const SettingsTabButton = ({ active, onClick, children }) => (
    <button
        type="button"
        className={cn(
            'settings-tab flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-[0.92rem] font-medium transition duration-200 ease-out md:justify-start',
            active
                ? 'active bg-interactive text-foreground'
                : 'text-foreground/70 hover:bg-interactive hover:text-foreground'
        )}
        onClick={onClick}
    >
        {children}
    </button>
);

const SettingsPane = ({ children, dataPane, className = '' }) => (
    <div
        className={cn(
            'settings-pane active ui-scrollbar-thin h-full overflow-x-hidden overflow-y-auto pr-1 sm:pr-2',
            className
        )}
        data-pane={dataPane}
    >
        {children}
    </div>
);

const SettingGroup = ({ title, description, children, className = '' }) => (
    <section className={cn('setting-group border-b border-border py-3 last:border-b-0', className)}>
        {title && (
            <h4 className="setting-group-title mb-2 text-base font-semibold text-foreground">
                {title}
            </h4>
        )}
        {description && (
            <p className="setting-group-description mb-3 text-sm leading-6 text-muted">
                {description}
            </p>
        )}
        {children}
    </section>
);

const SettingControlGroup = ({ children, className = '', withDivider = false }) => (
    <div
        className={cn(
            'setting-control-group flex flex-col gap-3 py-3 md:flex-row md:items-center md:justify-between',
            withDivider && 'border-t border-border',
            className
        )}
    >
        {children}
    </div>
);

const SettingField = ({ label, hint, children, className = '', withDivider = false }) => (
    <div className={cn('setting-field flex flex-col gap-1.5 py-2', withDivider && 'border-t border-border pt-4', className)}>
        <label className="text-sm font-medium text-foreground">{label}</label>
        {children}
        {hint && <span className="text-xs leading-5 text-subtle">{hint}</span>}
    </div>
);

const SettingToggle = ({ title, description, checked, onClick, ariaLabel, withDivider = false }) => (
    <div className={cn('setting-toggle flex items-start justify-between gap-4 py-3', withDivider && 'border-t border-border')}>
        <div className="setting-toggle-label min-w-0 space-y-1">
            <div className="setting-toggle-title text-[0.92rem] font-medium text-foreground">
                {title}
            </div>
            <p className="setting-toggle-description text-[0.82rem] leading-5 text-muted">
                {description}
            </p>
        </div>
        <ToggleSwitch checked={checked} onClick={onClick} ariaLabel={ariaLabel || title} />
    </div>
);

const SettingsModal = ({ onClose, onOpenAuth }) => {
    const { t, i18n } = useTranslation();
    const { settings, updateSetting } = useSettings();
    const { user, isAuthenticated, logout, updateProfile } = useAuth();
    const { getSettingsTab, navigateToSettings } = useURLRouter();

    const FONT_SIZE_MIN_PX = 10;
    const FONT_SIZE_MAX_PX = 24;
    const FONT_SIZE_STEP_PX = 2;
    const settingsInputClass = 'settings-input ui-input min-h-10 rounded-xl bg-interactive px-3.5 py-2.5';

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
    }, [settings.interface_language]); // eslint-disable-line react-hooks/exhaustive-deps

    const [activeTab, setActiveTab] = useState(() => {
        const tab = getSettingsTab();
        return tab || 'appearance';
    });
    const [username, setUsername] = useState('');
    const [isSavingProfile, setIsSavingProfile] = useState(false);
    const [profileMessage, setProfileMessage] = useState(null);

    useEffect(() => {
        if (user && user.username) {
            setUsername(user.username);
        }
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
            if (e.key === 'Escape') {
                onClose();
            }
        };

        document.addEventListener('keydown', handleEscapeKey);
        return () => document.removeEventListener('keydown', handleEscapeKey);
    }, [onClose]);

    useEffect(() => {
        if (!isAuthenticated && activeTab === 'personalization') {
            setActiveTab('appearance');
        }
    }, [activeTab, isAuthenticated]);

    const handleTabChange = (tab) => {
        setActiveTab(tab);
        navigateToSettings(tab, true);
    };

    const handleSaveProfile = async (e) => {
        e.preventDefault();
        if (!isAuthenticated) return;

        setIsSavingProfile(true);
        setProfileMessage(null);

        try {
            const res = await updateProfile({ username });
            if (res.success) {
                setProfileMessage({ type: 'success', text: t('settings.account.profileUpdated') });
            } else {
                setProfileMessage({ type: 'error', text: res.error || t('settings.account.updateError') });
            }
        } catch (err) {
            setProfileMessage({ type: 'error', text: err.message });
        } finally {
            setIsSavingProfile(false);
        }
    };

    const parsedFontSizePx = Number.parseInt(String(settings.fontSize || ''), 10);
    const currentFontSizePx = Number.isFinite(parsedFontSizePx)
        ? Math.min(FONT_SIZE_MAX_PX, Math.max(FONT_SIZE_MIN_PX, parsedFontSizePx))
        : 12;
    const fontSizePercent = ((currentFontSizePx - FONT_SIZE_MIN_PX) / (FONT_SIZE_MAX_PX - FONT_SIZE_MIN_PX)) * 100;

    const tabs = [
        {
            id: 'account',
            label: t('settings.tabs.account'),
            icon: (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
                    <circle cx="12" cy="7" r="4" />
                </svg>
            )
        },
        {
            id: 'appearance',
            label: t('settings.tabs.appearance'),
            icon: (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="13.5" cy="6.5" r="2.5" />
                    <path d="M13.5 2h-9A4.5 4.5 0 0 0 0 6.5v9A4.5 4.5 0 0 0 4.5 20h9a4.5 4.5 0 0 0 4.5-4.5v-9A4.5 4.5 0 0 0 13.5 2Z" />
                </svg>
            )
        },
        ...(isAuthenticated
            ? [{
                id: 'personalization',
                label: t('settings.tabs.personalization'),
                icon: (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="4" x2="4" y1="21" y2="14" />
                        <line x1="4" x2="4" y1="10" y2="3" />
                        <line x1="12" x2="12" y1="21" y2="12" />
                        <line x1="12" x2="12" y1="8" y2="3" />
                        <line x1="20" x2="20" y1="21" y2="16" />
                        <line x1="20" x2="20" y1="12" y2="3" />
                        <line x1="1" x2="7" y1="14" y2="14" />
                        <line x1="9" x2="15" y1="8" y2="8" />
                        <line x1="17" x2="23" y1="16" y2="16" />
                    </svg>
                )
            }]
            : []),
        {
            id: 'interface',
            label: t('settings.tabs.interface'),
            icon: (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect width="18" height="18" x="3" y="3" rx="2" ry="2" />
                    <line x1="9" x2="9" y1="3" y2="21" />
                </svg>
            )
        },
        {
            id: 'accessibility',
            label: t('settings.tabs.accessibility'),
            icon: (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="5" r="1" />
                    <path d="m9 20 3-6 3 6" />
                    <path d="m6 8 6 2 6-2" />
                    <path d="M12 10v4" />
                </svg>
            )
        }
    ];

    const renderAccountTab = () => (
        <SettingsPane dataPane="account">
            <SettingGroup className="account-overview">
                <div className="account-pane-header flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="space-y-1">
                        <h4 className="setting-group-title text-base font-semibold text-foreground">
                            {t('settings.account.title')}
                        </h4>
                        <p className="account-pane-description max-w-2xl text-sm leading-6 text-muted">
                            {t('settings.account.description')}
                        </p>
                    </div>
                    <span
                        className={cn(
                            'account-status-chip inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.08em]',
                            isAuthenticated
                                ? 'status-success border-[rgba(var(--color-success-raw),0.28)] bg-[rgba(var(--color-success-raw),0.12)] text-success'
                                : 'status-guest border-border-strong bg-interactive text-muted'
                        )}
                    >
                        {isAuthenticated ? t('settings.account.status.authorized') : t('settings.account.status.guest')}
                    </span>
                </div>

                <dl className="account-summary mt-4 grid gap-3 sm:grid-cols-3">
                    <div className="rounded-xl border border-border bg-surface-alt/70 px-4 py-3">
                        <dt className="text-xs font-semibold uppercase tracking-[0.08em] text-subtle">
                            {t('settings.account.fields.status')}
                        </dt>
                        <dd className="mt-2 text-sm font-medium text-foreground">
                            {isAuthenticated ? t('settings.account.signedIn') : t('settings.account.guestMode')}
                        </dd>
                    </div>
                    <div className="rounded-xl border border-border bg-surface-alt/70 px-4 py-3">
                        <dt className="text-xs font-semibold uppercase tracking-[0.08em] text-subtle">
                            {t('settings.account.fields.email')}
                        </dt>
                        <dd className="mt-2 break-all text-sm font-medium text-foreground">
                            {user?.email || t('settings.account.unavailable')}
                        </dd>
                    </div>
                    <div className="rounded-xl border border-border bg-surface-alt/70 px-4 py-3">
                        <dt className="text-xs font-semibold uppercase tracking-[0.08em] text-subtle">
                            {t('settings.account.fields.id')}
                        </dt>
                        <dd className="mt-2 text-sm font-medium text-foreground">
                            {user?.id || '-'}
                        </dd>
                    </div>
                </dl>
            </SettingGroup>

            <SettingGroup className="account-controls">
                {!isAuthenticated ? (
                    <div className="account-auth-cta flex flex-col gap-4 rounded-2xl border border-border bg-surface-alt/60 p-4 md:flex-row md:items-center md:justify-between">
                        <div className="space-y-1">
                            <h5 className="text-sm font-semibold text-foreground">
                                {t('settings.account.ctaTitle')}
                            </h5>
                            <p className="text-sm leading-6 text-muted">
                                {t('settings.account.ctaDescription')}
                            </p>
                        </div>
                        <button
                            type="button"
                            className="btn-primary ui-button-primary min-h-10 rounded-xl px-4 py-2.5"
                            onClick={() => { onClose(); onOpenAuth(); }}
                        >
                            {t('settings.account.signInOrRegister')}
                        </button>
                    </div>
                ) : (
                    <form className="account-form space-y-1" onSubmit={handleSaveProfile}>
                        <SettingField label={t('settings.account.fields.username')} className="account-field">
                            <input
                                className={settingsInputClass}
                                type="text"
                                id="accountUsernameInput"
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                maxLength="50"
                                required
                            />
                        </SettingField>

                        <SettingField
                            label="Email"
                            hint={t('settings.account.emailReadonlyHint')}
                            className="account-field"
                            withDivider
                        >
                            <input
                                className={cn(settingsInputClass, 'cursor-not-allowed opacity-75')}
                                type="email"
                                id="accountEmailInput"
                                value={user?.email || ''}
                                disabled
                            />
                        </SettingField>

                        <div className="account-actions flex flex-col gap-2 border-t border-border pt-4 sm:flex-row">
                            <button
                                type="submit"
                                className="btn-primary account-save-btn ui-button-primary min-h-10 rounded-xl px-4 py-2.5"
                                disabled={isSavingProfile}
                            >
                                {isSavingProfile ? t('settings.account.saving') : t('settings.account.saveChanges')}
                            </button>
                            <button
                                type="button"
                                className="account-secondary-btn ui-button-secondary min-h-10 rounded-xl px-4 py-2.5"
                                onClick={logout}
                            >
                                {t('settings.account.signOut')}
                            </button>
                        </div>

                        {profileMessage && (
                            <p
                                className={cn(
                                    'account-message is-visible rounded-xl border px-4 py-3 text-sm font-medium',
                                    profileMessage.type === 'success'
                                        ? 'border-[rgba(var(--color-success-raw),0.3)] bg-[rgba(var(--color-success-raw),0.12)] text-success'
                                        : 'border-[rgba(var(--color-error-raw),0.28)] bg-[rgba(var(--color-error-raw),0.12)] text-danger'
                                )}
                            >
                                {profileMessage.text}
                            </p>
                        )}
                    </form>
                )}
            </SettingGroup>
        </SettingsPane>
    );

    return (
        <ModalShell
            className="user-settings-modal active px-2 py-3 sm:px-4 sm:py-6"
            contentClassName="user-settings-content flex h-[85vh] min-h-[560px] w-full max-w-[1000px] flex-col rounded-[18px] border-border bg-surface shadow-[var(--shadow-xl)]"
            onBackdropClick={onClose}
        >
            <div className="user-settings-header flex items-center justify-between border-b border-border px-4 py-3 sm:px-5">
                <h3 className="text-[1.05rem] font-semibold tracking-[-0.01em] text-foreground">
                    {t('settings.title')}
                </h3>
                <button
                    className="user-settings-close ui-icon-control size-9 rounded-xl border-transparent bg-transparent text-muted hover:bg-interactive hover:text-foreground"
                    onClick={onClose}
                    aria-label={t('settings.close')}
                    type="button"
                >
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M18 6 6 18" />
                        <path d="m6 6 12 12" />
                    </svg>
                </button>
            </div>

            <div className="user-settings-body flex min-h-0 flex-1 flex-col overflow-hidden md:flex-row">
                <div className="settings-tabs ui-scrollbar-thin flex shrink-0 gap-1 overflow-x-auto border-b border-border bg-page p-2 md:w-60 md:flex-col md:overflow-y-auto md:border-b-0 md:border-r md:bg-surface-alt md:p-3">
                    {tabs.map((tab) => (
                        <SettingsTabButton
                            key={tab.id}
                            active={activeTab === tab.id}
                            onClick={() => handleTabChange(tab.id)}
                        >
                            {tab.icon}
                            <span>{tab.label}</span>
                        </SettingsTabButton>
                    ))}
                </div>

                <div className="settings-content min-h-0 flex-1 overflow-hidden bg-surface px-4 py-4 sm:px-5">
                    {activeTab === 'account' && renderAccountTab()}

                    {activeTab === 'appearance' && (
                        <SettingsPane>
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
                        <SettingsPane dataPane="personalization">
                            <SettingGroup
                                title={t('settings.personalization.title')}
                                description={t('settings.personalization.description')}
                            >
                                <SettingField label={t('settings.personalization.instructionsLabel')}>
                                    <textarea
                                        className={cn(settingsInputClass, 'min-h-32 resize-y')}
                                        rows="5"
                                        value={settings.personalization_instructions || ''}
                                        onChange={(e) => updateSetting('personalization_instructions', e.target.value)}
                                        placeholder={t('settings.personalization.instructionsPlaceholder')}
                                    />
                                </SettingField>
                                <SettingField label={t('settings.personalization.nicknameLabel')} withDivider>
                                    <input
                                        type="text"
                                        className={settingsInputClass}
                                        value={settings.personalization_nickname || ''}
                                        onChange={(e) => updateSetting('personalization_nickname', e.target.value)}
                                    />
                                </SettingField>
                                <SettingField label={t('settings.personalization.professionLabel')} withDivider>
                                    <input
                                        type="text"
                                        className={settingsInputClass}
                                        value={settings.personalization_profession || ''}
                                        onChange={(e) => updateSetting('personalization_profession', e.target.value)}
                                    />
                                </SettingField>
                                <SettingField label={t('settings.personalization.moreLabel')} withDivider>
                                    <textarea
                                        className={cn(settingsInputClass, 'min-h-24 resize-y')}
                                        rows="3"
                                        value={settings.personalization_more || ''}
                                        onChange={(e) => updateSetting('personalization_more', e.target.value)}
                                        placeholder={t('settings.personalization.morePlaceholder')}
                                    />
                                </SettingField>
                            </SettingGroup>
                        </SettingsPane>
                    )}

                    {activeTab === 'interface' && (
                        <SettingsPane>
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
                                    title={t('settings.interface.showSuggestions.title')}
                                    description={t('settings.interface.showSuggestions.description')}
                                    checked={settings.showSuggestions}
                                    onClick={() => updateSetting('showSuggestions', !settings.showSuggestions)}
                                    withDivider
                                />
                                <SettingToggle
                                    title={t('settings.interface.autocomplete.title')}
                                    description={t('settings.interface.autocomplete.description')}
                                    checked={settings.autocomplete}
                                    onClick={() => updateSetting('autocomplete', !settings.autocomplete)}
                                    withDivider
                                />
                            </SettingGroup>

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
                        <SettingsPane>
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
                </div>
            </div>
        </ModalShell>
    );
};

export default SettingsModal;
