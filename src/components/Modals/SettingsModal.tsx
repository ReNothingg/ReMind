import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useSettings } from '../../context/SettingsContext';
import { useAuth } from '../../context/AuthContext';
import { useURLRouter } from '../../hooks/useURLRouter';
import CustomSelect from '../UI/CustomSelect';
import { requestNotificationPermission } from '../../utils/notifications';
import { showToast } from '../../utils/toast';

const SettingsModal = ({ onClose, onOpenAuth }) => {
    const { t, i18n } = useTranslation();
    const { settings, updateSetting } = useSettings();
    const { user, isAuthenticated, logout, updateProfile } = useAuth();
    const { getSettingsTab, navigateToSettings } = useURLRouter();

    const FONT_SIZE_MIN_PX = 10;
    const FONT_SIZE_MAX_PX = 24;
    const FONT_SIZE_STEP_PX = 2;

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

    const handleBackdropClick = (e) => {
        if (e.target === e.currentTarget) onClose();
    };

    const parsedFontSizePx = Number.parseInt(String(settings.fontSize || ''), 10);
    const currentFontSizePx = Number.isFinite(parsedFontSizePx)
        ? Math.min(FONT_SIZE_MAX_PX, Math.max(FONT_SIZE_MIN_PX, parsedFontSizePx))
        : 12;
    const fontSizePercent = ((currentFontSizePx - FONT_SIZE_MIN_PX) / (FONT_SIZE_MAX_PX - FONT_SIZE_MIN_PX)) * 100;

    const renderAccountTab = () => (
        <div className="settings-pane active" data-pane="account">
            <div className="setting-group account-overview">
                <div className="account-pane-header">
                    <div>
                        <h4 className="setting-group-title">{t('settings.account.title')}</h4>
                        <p className="account-pane-description">
                            {t('settings.account.description')}
                        </p>
                    </div>
                    <span className={`account-status-chip ${isAuthenticated ? 'status-success' : 'status-guest'}`}>
                        {isAuthenticated ? t('settings.account.status.authorized') : t('settings.account.status.guest')}
                    </span>
                </div>
                <dl className="account-summary">
                    <div>
                        <dt>{t('settings.account.fields.status')}</dt>
                        <dd>{isAuthenticated ? t('settings.account.signedIn') : t('settings.account.guestMode')}</dd>
                    </div>
                    <div>
                        <dt>{t('settings.account.fields.email')}</dt>
                        <dd>{user?.email || t('settings.account.unavailable')}</dd>
                    </div>
                    <div>
                        <dt>{t('settings.account.fields.id')}</dt>
                        <dd>{user?.id || '-'}</dd>
                    </div>
                </dl>
            </div>

            <div className="setting-group account-controls">
                {!isAuthenticated ? (
                    <div className="account-auth-cta">
                        <div>
                            <h5>{t('settings.account.ctaTitle')}</h5>
                            <p>{t('settings.account.ctaDescription')}</p>
                        </div>
                        <button type="button" className="btn-primary" onClick={() => { onClose(); onOpenAuth(); }}>
                            {t('settings.account.signInOrRegister')}
                        </button>
                    </div>
                ) : (
                    <form className="account-form" onSubmit={handleSaveProfile}>
                        <div className="account-field">
                            <label htmlFor="accountUsernameInput">{t('settings.account.fields.username')}</label>
                            <input
                                className="settings-input"
                                type="text"
                                id="accountUsernameInput"
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                maxLength="50"
                                required
                            />
                        </div>

                        <div className="account-field">
                            <label htmlFor="accountEmailInput">Email</label>
                            <input
                                className="settings-input"
                                type="email"
                                id="accountEmailInput"
                                value={user?.email || ''}
                                disabled
                            />
                            <span className="account-field-hint">{t('settings.account.emailReadonlyHint')}</span>
                        </div>

                        <div className="account-actions">
                            <button type="submit" className="btn-primary account-save-btn" disabled={isSavingProfile}>
                                {isSavingProfile ? t('settings.account.saving') : t('settings.account.saveChanges')}
                            </button>
                            <button type="button" className="account-secondary-btn" onClick={logout}>
                                {t('settings.account.signOut')}
                            </button>
                        </div>

                        {profileMessage && (
                            <p className={`account-message is-visible ${profileMessage.type}`}>
                                {profileMessage.text}
                            </p>
                        )}
                    </form>
                )}
            </div>
        </div>
    );

    return (
        <div className="user-settings-modal active" onClick={handleBackdropClick}>
            <div className="user-settings-content">
                <div className="user-settings-header">
                    <h3>{t('settings.title')}</h3>
                    <button className="user-settings-close" onClick={onClose} aria-label={t('settings.close')}>
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg>
                    </button>
                </div>

                <div className="user-settings-body">
                    <div className="settings-tabs">
                        <button className={`settings-tab ${activeTab === 'account' ? 'active' : ''}`} onClick={() => handleTabChange('account')}>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
                            <span>{t('settings.tabs.account')}</span>
                        </button>
                        <button className={`settings-tab ${activeTab === 'appearance' ? 'active' : ''}`} onClick={() => handleTabChange('appearance')}>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="13.5" cy="6.5" r="2.5" /><path d="M13.5 2h-9A4.5 4.5 0 0 0 0 6.5v9A4.5 4.5 0 0 0 4.5 20h9a4.5 4.5 0 0 0 4.5-4.5v-9A4.5 4.5 0 0 0 13.5 2Z" /></svg>
                            <span>{t('settings.tabs.appearance')}</span>
                        </button>
                        {isAuthenticated && (
                            <button className={`settings-tab ${activeTab === 'personalization' ? 'active' : ''}`} onClick={() => handleTabChange('personalization')}>
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="4" x2="4" y1="21" y2="14" /><line x1="4" x2="4" y1="10" y2="3" /><line x1="12" x2="12" y1="21" y2="12" /><line x1="12" x2="12" y1="8" y2="3" /><line x1="20" x2="20" y1="21" y2="16" /><line x1="20" x2="20" y1="12" y2="3" /><line x1="1" x2="7" y1="14" y2="14" /><line x1="9" x2="15" y1="8" y2="8" /><line x1="17" x2="23" y1="16" y2="16" /></svg>
                                <span>{t('settings.tabs.personalization')}</span>
                            </button>
                        )}
                        <button className={`settings-tab ${activeTab === 'interface' ? 'active' : ''}`} onClick={() => handleTabChange('interface')}>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect width="18" height="18" x="3" y="3" rx="2" ry="2" /><line x1="9" x2="9" y1="3" y2="21" /></svg>
                            <span>{t('settings.tabs.interface')}</span>
                        </button>
                        <button className={`settings-tab ${activeTab === 'accessibility' ? 'active' : ''}`} onClick={() => handleTabChange('accessibility')}>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="5" r="1" /><path d="m9 20 3-6 3 6" /><path d="m6 8 6 2 6-2" /><path d="M12 10v4" /></svg>
                            <span>{t('settings.tabs.accessibility')}</span>
                        </button>
                    </div>

                    <div className="settings-content">

                        {}
                        {activeTab === 'account' && renderAccountTab()}

                        {}
                        {activeTab === 'appearance' && (
                            <div className="settings-pane active">
                                <div className="setting-group">
                                    <h4 className="setting-group-title">{t('settings.appearance.themeGroup')}</h4>
                                    <div className="setting-control-group">
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
                                    </div>
                                    <div className="setting-control-group">
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
                                    </div>
                                </div>
                                <div className="setting-group">
                                    <h4 className="setting-group-title">{t('settings.appearance.contentGroup')}</h4>
                                    <div className="setting-toggle">
                                        <div className="setting-toggle-label">
                                            <div className="setting-toggle-title">{t('settings.appearance.renderMarkdown.title')}</div>
                                            <p className="setting-toggle-description">{t('settings.appearance.renderMarkdown.description')}</p>
                                        </div>
                                        <button className={`toggle-switch ${settings.renderMarkdown ? 'active' : ''}`} onClick={() => updateSetting('renderMarkdown', !settings.renderMarkdown)}></button>
                                    </div>
                                    <div className="setting-toggle">
                                        <div className="setting-toggle-label">
                                            <div className="setting-toggle-title">{t('settings.appearance.snowBackground.title')}</div>
                                            <p className="setting-toggle-description">{t('settings.appearance.snowBackground.description')}</p>
                                        </div>
                                        <button className={`toggle-switch ${settings.snowBackground ? 'active' : ''}`} onClick={() => updateSetting('snowBackground', !settings.snowBackground)}></button>
                                    </div>
                                    <div className="setting-toggle">
                                        <div className="setting-toggle-label">
                                            <div className="setting-toggle-title">{t('settings.appearance.compactMode.title')}</div>
                                            <p className="setting-toggle-description">{t('settings.appearance.compactMode.description')}</p>
                                        </div>
                                        <button className={`toggle-switch ${settings.compactMode ? 'active' : ''}`} onClick={() => updateSetting('compactMode', !settings.compactMode)}></button>
                                    </div>
                                </div>
                            </div>
                        )}

                        {}
                        {activeTab === 'personalization' && (
                            <div className="settings-pane active" data-pane="personalization">
                                <div className="setting-group">
                                    <h4 className="setting-group-title">{t('settings.personalization.title')}</h4>
                                    <p className="setting-group-description">{t('settings.personalization.description')}</p>

                                    <div className="setting-field">
                                        <label>{t('settings.personalization.instructionsLabel')}</label>
                                        <textarea
                                            className="settings-input"
                                            rows="5"
                                            value={settings.personalization_instructions || ''}
                                            onChange={(e) => updateSetting('personalization_instructions', e.target.value)}
                                            placeholder={t('settings.personalization.instructionsPlaceholder')}
                                        ></textarea>
                                    </div>
                                    <div className="setting-field">
                                        <label>{t('settings.personalization.nicknameLabel')}</label>
                                        <input
                                            type="text"
                                            className="settings-input"
                                            value={settings.personalization_nickname || ''}
                                            onChange={(e) => updateSetting('personalization_nickname', e.target.value)}
                                        />
                                    </div>
                                    <div className="setting-field">
                                        <label>{t('settings.personalization.professionLabel')}</label>
                                        <input
                                            type="text"
                                            className="settings-input"
                                            value={settings.personalization_profession || ''}
                                            onChange={(e) => updateSetting('personalization_profession', e.target.value)}
                                        />
                                    </div>
                                    <div className="setting-field">
                                        <label>{t('settings.personalization.moreLabel')}</label>
                                        <textarea
                                            className="settings-input"
                                            rows="3"
                                            value={settings.personalization_more || ''}
                                            onChange={(e) => updateSetting('personalization_more', e.target.value)}
                                            placeholder={t('settings.personalization.morePlaceholder')}
                                        ></textarea>
                                    </div>
                                </div>
                            </div>
                        )}

                        {}
                        {activeTab === 'interface' && (
                            <div className="settings-pane active">
                                <div className="setting-group">
                                    <h4 className="setting-group-title">{t('settings.interfaceLanguage.title')}</h4>
                                    <div className="setting-control-group">
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
                                    </div>
                                    {}
                                </div>
                                <div className="setting-group">
                                    <h4 className="setting-group-title">{t('settings.interface.navigationGroup')}</h4>
                                    <div className="setting-toggle">
                                        <div className="setting-toggle-label">
                                            <div className="setting-toggle-title">{t('settings.interface.showChatPreview.title')}</div>
                                            <p className="setting-toggle-description">{t('settings.interface.showChatPreview.description')}</p>
                                        </div>
                                        <button className={`toggle-switch ${settings.showChatPreview ? 'active' : ''}`} onClick={() => updateSetting('showChatPreview', !settings.showChatPreview)}></button>
                                    </div>
                                    <div className="setting-toggle">
                                        <div className="setting-toggle-label">
                                            <div className="setting-toggle-title">{t('settings.interface.showSuggestions.title')}</div>
                                            <p className="setting-toggle-description">{t('settings.interface.showSuggestions.description')}</p>
                                        </div>
                                        <button className={`toggle-switch ${settings.showSuggestions ? 'active' : ''}`} onClick={() => updateSetting('showSuggestions', !settings.showSuggestions)}></button>
                                    </div>
                                    <div className="setting-toggle">
                                        <div className="setting-toggle-label">
                                            <div className="setting-toggle-title">{t('settings.interface.autocomplete.title')}</div>
                                            <p className="setting-toggle-description">{t('settings.interface.autocomplete.description')}</p>
                                        </div>
                                        <button className={`toggle-switch ${settings.autocomplete ? 'active' : ''}`} onClick={() => updateSetting('autocomplete', !settings.autocomplete)}></button>
                                    </div>
                                </div>
                                <div className="setting-group">
                                    <h4 className="setting-group-title">{t('settings.interface.behaviorGroup')}</h4>
                                    <div className="setting-toggle">
                                        <div className="setting-toggle-label">
                                            <div className="setting-toggle-title">{t('settings.interface.autoscroll.title')}</div>
                                            <p className="setting-toggle-description">{t('settings.interface.autoscroll.description')}</p>
                                        </div>
                                        <button className={`toggle-switch ${settings.autoscroll ? 'active' : ''}`} onClick={() => updateSetting('autoscroll', !settings.autoscroll)}></button>
                                    </div>
                                    <div className="setting-toggle">
                                        <div className="setting-toggle-label">
                                            <div className="setting-toggle-title">{t('settings.interface.notifyOnThinkingDone.title')}</div>
                                            <p className="setting-toggle-description">{t('settings.interface.notifyOnThinkingDone.description')}</p>
                                        </div>
                                        <button
                                            className={`toggle-switch ${settings.notifyOnThinkingDone ? 'active' : ''}`}
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
                                        ></button>
                                    </div>
                                    <div className="setting-toggle">
                                        <div className="setting-toggle-label">
                                            <div className="setting-toggle-title">{t('settings.interface.requireCtrlEnter.title')}</div>
                                            <p className="setting-toggle-description">{t('settings.interface.requireCtrlEnter.description')}</p>
                                        </div>
                                        <button className={`toggle-switch ${settings.requireCtrlEnterToSend ? 'active' : ''}`} onClick={() => updateSetting('requireCtrlEnterToSend', !settings.requireCtrlEnterToSend)}></button>
                                    </div>
                                    <div className="setting-toggle">
                                        <div className="setting-toggle-label">
                                            <div className="setting-toggle-title">{t('settings.interface.renderUserMarkdown.title')}</div>
                                            <p className="setting-toggle-description">{t('settings.interface.renderUserMarkdown.description')}</p>
                                        </div>
                                        <button className={`toggle-switch ${settings.renderUserMarkdown ? 'active' : ''}`} onClick={() => updateSetting('renderUserMarkdown', !settings.renderUserMarkdown)}></button>
                                    </div>
                                    <div className="setting-toggle">
                                        <div className="setting-toggle-label">
                                            <div className="setting-toggle-title">{t('settings.interface.autoSave.title')}</div>
                                            <p className="setting-toggle-description">{t('settings.interface.autoSave.description')}</p>
                                        </div>
                                        <button className={`toggle-switch ${settings.autoSave ? 'active' : ''}`} onClick={() => updateSetting('autoSave', !settings.autoSave)}></button>
                                    </div>
                                </div>
                            </div>
                        )}

                        {}
                        {activeTab === 'accessibility' && (
                            <div className="settings-pane active">
                                <div className="setting-group">
                                    <h4 className="setting-group-title">{t('settings.accessibility.typographyGroup')}</h4>
                                    <div className="setting-control-group">
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
	                                    </div>
	                                    <div className="setting-control-group">
	                                        <div className="setting-range-wrapper">
	                                            <div className="setting-range-label">{t('settings.accessibility.fontSizeLabel')}</div>
	                                            <div className="setting-range-control">
	                                                <div
	                                                    className="setting-range-bubble"
	                                                    style={{ left: `${fontSizePercent}%` }}
	                                                    aria-hidden="true"
	                                                >
	                                                    {currentFontSizePx}px
	                                                </div>
	                                                <input
	                                                    className="setting-range"
	                                                    type="range"
	                                                    min={FONT_SIZE_MIN_PX}
	                                                    max={FONT_SIZE_MAX_PX}
	                                                    step={FONT_SIZE_STEP_PX}
	                                                    value={currentFontSizePx}
	                                                    onChange={(e) => updateSetting('fontSize', `${e.target.value}px`)}
	                                                    aria-label={t('settings.accessibility.fontSizeLabel')}
	                                                />
	                                                <div className="setting-range-ticks" aria-hidden="true">
	                                                    {Array.from(
	                                                        { length: Math.floor((FONT_SIZE_MAX_PX - FONT_SIZE_MIN_PX) / FONT_SIZE_STEP_PX) + 1 },
	                                                        (_, i) => FONT_SIZE_MIN_PX + i * FONT_SIZE_STEP_PX
	                                                    ).map((v) => (
	                                                        <span key={v} className="setting-range-tick" />
	                                                    ))}
	                                                </div>
	                                                <div className="setting-range-meta">
	                                                    <span>{FONT_SIZE_MIN_PX}px</span>
	                                                    <span>{FONT_SIZE_MAX_PX}px</span>
	                                                </div>
	                                            </div>
	                                        </div>
	                                    </div>
	                                </div>
                                <div className="setting-group">
                                    <h4 className="setting-group-title">{t('settings.accessibility.accessibilityGroup')}</h4>
                                    <div className="setting-toggle">
                                        <div className="setting-toggle-label">
                                            <div className="setting-toggle-title">{t('settings.accessibility.keyboardSupport.title')}</div>
                                            <p className="setting-toggle-description">{t('settings.accessibility.keyboardSupport.description')}</p>
                                        </div>
                                        <button className={`toggle-switch ${settings.keyboardSupport ? 'active' : ''}`} onClick={() => updateSetting('keyboardSupport', !settings.keyboardSupport)}></button>
                                    </div>
                                    <div className="setting-toggle">
                                        <div className="setting-toggle-label">
                                            <div className="setting-toggle-title">{t('settings.accessibility.highContrast.title')}</div>
                                            <p className="setting-toggle-description">{t('settings.accessibility.highContrast.description')}</p>
                                        </div>
                                        <button className={`toggle-switch ${settings.highContrast ? 'active' : ''}`} onClick={() => updateSetting('highContrast', !settings.highContrast)}></button>
                                    </div>
                                </div>
                                <div className="setting-group">
                                    <h4 className="setting-group-title">{t('settings.accessibility.codeGroup')}</h4>
                                    <div className="setting-toggle">
                                        <div className="setting-toggle-label">
                                            <div className="setting-toggle-title">{t('settings.accessibility.codeWrap.title')}</div>
                                            <p className="setting-toggle-description">{t('settings.accessibility.codeWrap.description')}</p>
                                        </div>
                                        <button className={`toggle-switch ${settings.codeWrap ? 'active' : ''}`} onClick={() => updateSetting('codeWrap', !settings.codeWrap)}></button>
                                    </div>
                                </div>
                            </div>
                        )}

                    </div>
                </div>
            </div>
        </div>
    );
};

export default SettingsModal;
