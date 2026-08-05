import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, X } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { authService } from '../../services/auth';
import { apiService } from '../../services/api';
import { loadTelegramLoginSdk } from '../../services/telegramLogin';
import SocialAuthButton, { GoogleLogo, TelegramLogo } from '../Auth/SocialAuthButton';
import ModalShell from '../UI/ModalShell';
import { cn } from '../../utils/cn';
import {
    firstAccountFieldError,
    localizeAccountError,
    type AccountFieldErrors,
    validateAccountName,
    validateUsername,
} from '../../utils/accountValidation';

const PASSWORD_STRENGTH_COLORS = [
    'var(--color-text-tertiary)',
    'var(--color-error)',
    'var(--color-warning)',
    'var(--color-accent)',
    'var(--color-success)',
];

type AuthModalMode = 'login' | 'register' | 'link';

type AuthModalProps = {
    onClose: () => void;
    initialView?: Exclude<AuthModalMode, 'link'>;
    authMode?: AuthModalMode;
};

const getPasswordStrength = (value: string) => {
    if (!value) {
        return { score: 0, level: 'empty' };
    }

    let score = 0;
    const hasLower = /[a-z]/.test(value);
    const hasUpper = /[A-Z]/.test(value);
    const hasNumber = /\d/.test(value);
    const hasSymbol = /[^\sA-Za-z0-9]/.test(value);
    const uniqueCharacters = new Set(value).size;

    if (value.length >= 8) score += 1;
    if (value.length >= 12) score += 1;
    if (hasLower && hasUpper) score += 1;
    if (hasNumber) score += 1;
    if (hasSymbol) score += 1;
    if (value.length >= 8 && uniqueCharacters < 5) score -= 1;

    score = Math.max(1, Math.min(score, 4));

    if (score >= 4) return { score, level: 'strong' };
    if (score === 3) return { score, level: 'good' };
    if (score === 2) return { score, level: 'fair' };
    return { score, level: 'weak' };
};

const AuthModal = ({ onClose, initialView = 'login', authMode }: AuthModalProps) => {
    const { t, i18n } = useTranslation();
    const { login, loginWithTelegram, checkAuth, isAuthenticated } = useAuth();
    const linkMode = authMode === 'link';
    const [isLoginView, setIsLoginView] = useState(initialView === 'login' || linkMode);
    const [isLoading, setIsLoading] = useState(false);
    const [message, setMessage] = useState(null);
    const [authConfig, setAuthConfig] = useState(null);
    const [googleUrl, setGoogleUrl] = useState('/login/google');
    const [googleAvailable, setGoogleAvailable] = useState(false);
    const [telegramSdkReady, setTelegramSdkReady] = useState(false);
    const [telegramLoading, setTelegramLoading] = useState(false);
    const loginTurnstileIdRef = useRef(undefined);
    const registerTurnstileIdRef = useRef(undefined);
    const authConfigRequestStartedRef = useRef(false);
    const loginContainerRef = useRef(null);
    const registerContainerRef = useRef(null);
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [name, setName] = useState('');
    const [username, setUsername] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [showPassword, setShowPassword] = useState(false);
    const [showConfirmPassword, setShowConfirmPassword] = useState(false);
    const [fieldErrors, setFieldErrors] = useState<AccountFieldErrors>({});

    const fieldLabelClass = 'ui-field-label';
    const fieldInputClass = 'ui-input min-h-10 rounded-md bg-interactive px-4 py-2.5 text-[0.94rem]';
    const primaryButtonClass = 'btn-primary btn-block ui-button-primary min-h-10 w-full justify-center rounded-md px-4 py-2.5 text-[0.94rem] font-semibold';
    const telegramAvailable = Boolean(
        authConfig?.telegram_available
        && authConfig?.telegram_client_id
        && authConfig?.telegram_nonce
    );
    const shouldUseTurnstile = Boolean(authConfig?.turnstile_site_key) && authConfig?.turnstile_required !== false;
    const passwordStrength = getPasswordStrength(password);
    const passwordStrengthColor = PASSWORD_STRENGTH_COLORS[passwordStrength.score];
    const passwordToggleLabel = showPassword
        ? t('authModal.actions.hidePassword')
        : t('authModal.actions.showPassword');
    const confirmPasswordToggleLabel = showConfirmPassword
        ? t('authModal.actions.hidePassword')
        : t('authModal.actions.showPassword');

    const getTurnstileResponse = (idRef) => {
        try {
            if (window.turnstile && idRef.current !== undefined) {
                return window.turnstile.getResponse(idRef.current) || null;
            }
        } catch (error) {
            console.warn('Failed to get Turnstile response', error);
        }
        return null;
    };

    const hasRequiredTurnstileToken = (token) => {
        if (!shouldUseTurnstile || token) {
            return true;
        }
        setMessage({ type: 'error', text: t('authModal.messages.turnstileRequired') });
        return false;
    };

    const removeTurnstile = (idRef, containerRef) => {
        if (!window.turnstile) return;
        if (idRef.current !== undefined) {
            try {
                window.turnstile.remove(idRef.current);
            } catch (err) {
                console.warn('Failed to remove Turnstile:', err);
            }
            idRef.current = undefined;
        }
        if (containerRef?.current) {
            containerRef.current.innerHTML = '';
        }
    };

    const googleHref = (() => {
        try {
            const base = new URL(googleUrl, window.location.origin);
            base.searchParams.set('redirect_to', window.location.href);
            return base.toString();
        } catch {
            const separator = googleUrl.includes('?') ? '&' : '?';
            return `${googleUrl}${separator}redirect_to=${encodeURIComponent(window.location.href)}`;
        }
    })();

    useEffect(() => {
        setIsLoginView(initialView === 'login' || linkMode);
    }, [initialView, linkMode]);

    useEffect(() => {
        if (!linkMode) return;
        if (isAuthenticated) return;
        setMessage({ type: 'error', text: t('settings.account.loginMethods.authRequired') });
    }, [isAuthenticated, linkMode, t]);

    useEffect(() => {
        if (authConfigRequestStartedRef.current) return;
        authConfigRequestStartedRef.current = true;

        const loadAuthConfig = async () => {
            try {
                const resp = await fetch(`${apiService.baseURL}/api/auth/config`, {
                    method: 'GET',
                    credentials: 'include'
                });
                if (!resp.ok) return;
                const cfg = await resp.json();
                setAuthConfig(cfg);
                setGoogleUrl(cfg.google_login_url || '/login/google');
                setGoogleAvailable(cfg.gauth_available || false);
            } catch (err) {
                console.warn('Failed to load auth config', err);
            }
        };
        loadAuthConfig();
    }, []);

    useEffect(() => {
        if (!telegramAvailable) {
            setTelegramSdkReady(false);
            return;
        }

        let cancelled = false;
        loadTelegramLoginSdk()
            .then(() => {
                if (!cancelled) setTelegramSdkReady(true);
            })
            .catch((error) => {
                console.warn('Telegram Login SDK failed to load', error);
                if (!cancelled) {
                    setTelegramSdkReady(false);
                    setMessage({
                        type: 'error',
                        text: t('authModal.messages.telegramUnavailable'),
                    });
                }
            });

        return () => {
            cancelled = true;
        };
    }, [telegramAvailable, t]);

    const handleTelegramLogin = () => {
        if (!telegramAvailable || !telegramSdkReady || telegramLoading) return;

        setTelegramLoading(true);
        setMessage(null);

        try {
            const clientId = Number(authConfig.telegram_client_id);
            if (!Number.isSafeInteger(clientId) || clientId <= 0 || !window.Telegram?.Login) {
                throw new Error('telegram_config_invalid');
            }

            window.Telegram.Login.auth(
                {
                    client_id: clientId,
                    scope: ['profile', 'write'],
                    lang: String(i18n.resolvedLanguage || i18n.language || 'en').split('-')[0],
                    nonce: authConfig.telegram_nonce,
                },
                async (result) => {
                    try {
                        if (result.error || !result.id_token) {
                            setMessage({ type: 'error', text: t('authModal.messages.telegramError') });
                            return;
                        }

                        const response = linkMode
                            ? await authService.linkTelegram(result.id_token)
                            : await loginWithTelegram(result.id_token);
                        if (!response.success) {
                            if (linkMode) {
                                const responseError = ('error' in response ? response.error : '') || '';
                                const isConflict = responseError === 'auth_identity_in_use'
                                    || responseError === 'identity_in_use'
                                    || responseError === 'auth_provider_already_linked';
                                const isSessionLost = responseError === 'auth_required';
                                setMessage({
                                    type: 'error',
                                    text: isSessionLost
                                        ? t('settings.account.loginMethods.authRequired')
                                        : isConflict
                                            ? t('settings.account.loginMethods.identityInUse')
                                            : t('settings.account.loginMethods.telegramFailed'),
                                });
                            } else {
                                setMessage({ type: 'error', text: t('authModal.messages.telegramError') });
                            }
                            return;
                        }

                        if (linkMode) {
                            const authState = await checkAuth();
                            if (!authState.authenticated) {
                                setMessage({
                                    type: 'error',
                                    text: t('settings.account.loginMethods.authRequired'),
                                });
                                return;
                            }
                            setMessage({
                                type: 'success',
                                text: t('settings.account.loginMethods.telegramLinked'),
                            });
                            setTimeout(() => {
                                onClose();
                            }, 1500);
                        }
                    } catch (error) {
                        console.warn('Telegram Login failed', error);
                        setMessage({ type: 'error', text: t('authModal.messages.telegramUnavailable') });
                    } finally {
                        setTelegramLoading(false);
                    }
                }
            );
        } catch (error) {
            console.warn('Telegram Login failed to start', error);
            setMessage({ type: 'error', text: t('authModal.messages.telegramUnavailable') });
            setTelegramLoading(false);
        }
    };

    const renderTelegramLogin = () => {
        if (!telegramAvailable) return null;
        const labelKey = linkMode
            ? 'settings.account.loginMethods.linkTelegram'
            : isLoginView
                ? 'authModal.actions.loginWithTelegram'
                : 'authModal.actions.registerWithTelegram';
        const loadingKey = linkMode ? 'settings.account.loginMethods.linkingTelegram' : 'authModal.actions.telegramLoading';

        return (
            <SocialAuthButton
                onClick={handleTelegramLogin}
                disabled={!telegramSdkReady || telegramLoading || isLoading}
                busy={!telegramSdkReady || telegramLoading}
                label={t(labelKey)}
                icon={<TelegramLogo />}
            >
                {!telegramSdkReady || telegramLoading ? t(loadingKey) : t(labelKey)}
            </SocialAuthButton>
        );
    };

    const waitForTurnstile = async (maxRetries = 50, delayMs = 100) => {
        for (let i = 0; i < maxRetries; i++) {
            if (window.turnstile) {
                return true;
            }
            await new Promise(resolve => setTimeout(resolve, delayMs));
        }
        console.warn(`Turnstile script failed to load after ${maxRetries * delayMs}ms`);
        return false;
    };

    useEffect(() => {
        if (!shouldUseTurnstile) return;
        let timeoutId;
        let cancelled = false;

        const initTurnstile = async () => {
            const loaded = await waitForTurnstile();
            if (cancelled) return;
            if (!loaded || !window.turnstile) {
                setMessage({ type: 'error', text: t('authModal.messages.turnstileLoadError') });
                return;
            }
            const targetRef = isLoginView ? loginContainerRef : registerContainerRef;
            const idRef = isLoginView ? loginTurnstileIdRef : registerTurnstileIdRef;
            const renderTurnstile = () => {
                if (cancelled || !targetRef.current) return;
                removeTurnstile(idRef, targetRef);
                try {
                    idRef.current = window.turnstile.render(targetRef.current, {
                        sitekey: authConfig.turnstile_site_key,
                        theme: 'dark',
                        size: 'normal',
                        appearance: 'always',
                        execution: 'render',
                        'error-callback': (errorCode) => {
                            if (isLoginView) {
                                console.error('Turnstile error (login)', errorCode);
                            } else {
                                console.error('Turnstile error (register)', errorCode);
                            }
                            if (!cancelled) {
                                setMessage({ type: 'error', text: t('authModal.messages.turnstileLoadError') });
                            }
                        }
                    });
                } catch (err) {
                    if (isLoginView) {
                        console.warn('Failed to render login Turnstile:', err);
                    } else {
                        console.warn('Failed to render register Turnstile:', err);
                    }
                    if (!cancelled) {
                        setMessage({ type: 'error', text: t('authModal.messages.turnstileLoadError') });
                    }
                }
            };

            timeoutId = setTimeout(() => {
                renderTurnstile();
            }, 100);
        };

        initTurnstile();
        return () => {
            cancelled = true;
            if (timeoutId !== undefined) clearTimeout(timeoutId);
        };
    }, [authConfig, isLoginView, shouldUseTurnstile, t]);

    useEffect(() => {
        if (!window.turnstile) return;

        return () => {
            if (isLoginView) {
                removeTurnstile(loginTurnstileIdRef, loginContainerRef);
            } else {
                removeTurnstile(registerTurnstileIdRef, registerContainerRef);
            }
        };
    }, [isLoginView]);

    const handleLogin = async (e) => {
        e.preventDefault();
        setIsLoading(true);
        setMessage(null);
        setFieldErrors({});

        try {
            const turnstileResponse = getTurnstileResponse(loginTurnstileIdRef);
            if (!hasRequiredTurnstileToken(turnstileResponse)) {
                return;
            }

            const res = await login(email, password, turnstileResponse);
            if (res.success === false) {
                try {
                    if (window.turnstile && loginTurnstileIdRef.current !== undefined) {
                        window.turnstile.reset(loginTurnstileIdRef.current);
                    }
                } catch {
                }
                setMessage({ type: 'error', text: res.error || t('authModal.messages.loginError') });
                return;
            }

            setMessage({ type: 'success', text: res.message || t('authModal.messages.loginSuccess') });
            try {
                if (window.turnstile && loginTurnstileIdRef.current !== undefined) {
                    window.turnstile.reset(loginTurnstileIdRef.current);
                }
            } catch {
            }
            setTimeout(() => {
                onClose();
            }, 1500);
        } catch {
            setMessage({ type: 'error', text: t('authModal.messages.requestError') });
        } finally {
            setIsLoading(false);
        }
    };

    const handleRegister = async (e) => {
        e.preventDefault();
        setFieldErrors({});

        const nextFieldErrors: AccountFieldErrors = {};
        const nameError = validateAccountName(name, t, { required: true });
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
            setMessage({ type: 'error', text: firstError });
            return;
        }

        if (password !== confirmPassword) {
            setMessage({ type: 'error', text: t('authModal.messages.passwordsMismatch') });
            return;
        }
        if (name.length > 100) {
            setMessage({ type: 'error', text: t('settings.account.validation.nameLength') });
            return;
        }
        if (username.length > 100) {
            setMessage({ type: 'error', text: t('authModal.messages.usernameTooLong') });
            return;
        }
        if (email.length > 100) {
            setMessage({ type: 'error', text: t('authModal.messages.emailTooLong') });
            return;
        }
        if (password.length > 100) {
            setMessage({ type: 'error', text: t('authModal.messages.passwordTooLong') });
            return;
        }

        setIsLoading(true);
        setMessage(null);

        try {
            const turnstileResponse = getTurnstileResponse(registerTurnstileIdRef);
            if (!hasRequiredTurnstileToken(turnstileResponse)) {
                return;
            }

            const res = await authService.register(name.trim(), username.trim(), email, password, turnstileResponse);
            if (res.success === false) {
                const localizedError = localizeAccountError(res.error, res.field, t);
                setFieldErrors(localizedError.fieldErrors);
                try {
                    if (window.turnstile && registerTurnstileIdRef.current !== undefined) {
                        window.turnstile.reset(registerTurnstileIdRef.current);
                    }
                } catch {
                }
                setMessage({ type: 'error', text: localizedError.message || t('authModal.messages.registerError') });
                return;
            }

            setFieldErrors({});
            setMessage({ type: 'success', text: res.message || t('authModal.messages.registerSuccess') });
            try {
                if (window.turnstile && registerTurnstileIdRef.current !== undefined) {
                    window.turnstile.reset(registerTurnstileIdRef.current);
                }
            } catch {
            }
            setTimeout(() => {
                setIsLoginView(true);
                setMessage(null);
            }, 2000);
        } catch {
            setMessage({ type: 'error', text: t('authModal.messages.requestError') });
        } finally {
            setIsLoading(false);
        }
    };

    const switchView = (e) => {
        if (linkMode) return;
        e.preventDefault();
        setIsLoginView(!isLoginView);
        setMessage(null);
        setFieldErrors({});
        setEmail('');
        setPassword('');
        setName('');
        setUsername('');
        setConfirmPassword('');
        setShowPassword(false);
        setShowConfirmPassword(false);
    };

    return (
        <ModalShell
            ariaLabel={t(isLoginView ? 'authModal.loginTitle' : 'authModal.registerTitle')}
            className="auth-modal items-end px-0 py-0 sm:items-center sm:px-4 sm:py-6"
            contentClassName="auth-modal-content mx-auto w-full max-w-[460px] rounded-t-xl border-border bg-surface px-5 pb-6 pt-5 text-foreground sm:rounded-xl sm:px-6 sm:pb-6 sm:pt-6"
            onRequestClose={onClose}
        >
            <button
                className="auth-modal-close ui-icon-control absolute right-4 top-4 size-10 rounded-md border-transparent bg-interactive text-muted hover:bg-surface-alt hover:text-foreground"
                onClick={onClose}
                aria-label={t('translationPanel.close')}
                type="button"
            >
                <X size={20} strokeWidth={1.9} aria-hidden="true" />
            </button>

            {isLoginView ? (
                <div className="auth-form space-y-4">
                    <div className="space-y-1 pr-12">
                        <h2 className="text-[1.45rem] font-bold tracking-normal text-foreground">
                            {t('authModal.loginTitle')}
                        </h2>
                    </div>

                    <form className="space-y-4" onSubmit={handleLogin}>
                        <div className="form-group flex flex-col gap-1.5">
                            <label className={fieldLabelClass} htmlFor="loginEmail">{t('authModal.fields.email')}</label>
                            <input
                                className={fieldInputClass}
                                type="email"
                                id="loginEmail"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                            />
                        </div>
                        <div className="form-group flex flex-col gap-1.5">
                            <label className={fieldLabelClass} htmlFor="loginPassword">{t('authModal.fields.password')}</label>
                            <div className="password-field">
                                <input
                                    className={`${fieldInputClass} auth-password-input`}
                                    type={showPassword ? 'text' : 'password'}
                                    id="loginPassword"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                />
                                <button
                                    className="password-toggle"
                                    type="button"
                                    onClick={() => setShowPassword((current) => !current)}
                                    aria-label={passwordToggleLabel}
                                    aria-pressed={showPassword}
                                    title={passwordToggleLabel}
                                >
                                    {showPassword ? <EyeOff className="password-toggle__icon" size={18} aria-hidden="true" /> : <Eye className="password-toggle__icon" size={18} aria-hidden="true" />}
                                </button>
                            </div>
                        </div>

                        {shouldUseTurnstile && (
                            <div
                                id="loginTurnstileContainer"
                                ref={loginContainerRef}
                                className="recaptcha-container overflow-x-auto"
                            />
                        )}

                        <button type="submit" className={primaryButtonClass} disabled={isLoading}>
                            {isLoading ? t('authModal.actions.loginLoading') : t('auth.login')}
                        </button>

                        {(googleAvailable || telegramAvailable) && (
                            <div className="space-y-2 pt-1">
                                {googleAvailable && (
                                    <SocialAuthButton
                                        href={googleHref}
                                        label={t('authModal.actions.loginWithGoogle')}
                                        icon={<GoogleLogo />}
                                    >
                                        {t('authModal.actions.loginWithGoogle')}
                                    </SocialAuthButton>
                                )}
                                {renderTelegramLogin()}
                            </div>
                        )}
                    </form>

                    {!linkMode && (
                        <p className="auth-switch-link text-center text-sm text-muted">
                            {t('authModal.switch.noAccount')}{' '}
                            <button className="auth-switch-action font-semibold text-[var(--color-text-link)] hover:underline" type="button" onClick={switchView}>
                                {t('auth.register')}
                            </button>
                        </p>
                    )}
                </div>
            ) : (
                <div className="auth-form auth-register-panel space-y-4">
                    <div className="space-y-1 pr-12">
                        <h2 className="text-[1.45rem] font-bold tracking-normal text-foreground">
                            {t('authModal.registerTitle')}
                        </h2>
                    </div>

                    <form className="auth-register-form" onSubmit={handleRegister}>
                        <div className="form-group flex flex-col gap-1.5">
                            <label className={fieldLabelClass} htmlFor="regName">{t('authModal.fields.name')}</label>
                            <input
                                className={fieldInputClass}
                                type="text"
                                id="regName"
                                value={name}
                                onChange={(e) => {
                                    setName(e.target.value);
                                    setFieldErrors((prev) => ({ ...prev, name: undefined }));
                                }}
                                maxLength={100}
                                required
                                aria-invalid={!!fieldErrors.name}
                                aria-describedby={fieldErrors.name ? 'regNameError' : undefined}
                            />
                            {fieldErrors.name && (
                                <p id="regNameError" className="text-sm font-medium text-danger">{fieldErrors.name}</p>
                            )}
                        </div>
                        <div className="form-group flex flex-col gap-1.5">
                            <label className={fieldLabelClass} htmlFor="regUsername">{t('authModal.fields.username')}</label>
                            <input
                                className={fieldInputClass}
                                type="text"
                                id="regUsername"
                                value={username}
                                onChange={(e) => {
                                    setUsername(e.target.value);
                                    setFieldErrors((prev) => ({ ...prev, username: undefined }));
                                }}
                                maxLength={50}
                                required
                                aria-invalid={!!fieldErrors.username}
                                aria-describedby={fieldErrors.username ? 'regUsernameError' : undefined}
                            />
                            {fieldErrors.username && (
                                <p id="regUsernameError" className="text-sm font-medium text-danger">{fieldErrors.username}</p>
                            )}
                        </div>
                        <div className="form-group auth-field-full flex flex-col gap-1.5">
                            <label className={fieldLabelClass} htmlFor="regEmail">{t('authModal.fields.email')}</label>
                            <input
                                className={fieldInputClass}
                                type="email"
                                id="regEmail"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                maxLength={100}
                                required
                            />
                        </div>
                        <div className="form-group flex flex-col gap-1.5">
                            <label className={fieldLabelClass} htmlFor="regPassword">{t('authModal.fields.password')}</label>
                            <div className="password-field">
                                <input
                                    className={`${fieldInputClass} auth-password-input`}
                                    type={showPassword ? 'text' : 'password'}
                                    id="regPassword"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    minLength={8}
                                    maxLength={100}
                                    required
                                />
                                <button
                                    className="password-toggle"
                                    type="button"
                                    onClick={() => setShowPassword((current) => !current)}
                                    aria-label={passwordToggleLabel}
                                    aria-pressed={showPassword}
                                    title={passwordToggleLabel}
                                >
                                    {showPassword ? <EyeOff className="password-toggle__icon" size={18} aria-hidden="true" /> : <Eye className="password-toggle__icon" size={18} aria-hidden="true" />}
                                </button>
                            </div>
                        </div>
                        <div className="form-group flex flex-col gap-1.5">
                            <label className={fieldLabelClass} htmlFor="regConfirm">{t('authModal.fields.confirmPassword')}</label>
                            <div className="password-field">
                                <input
                                    className={`${fieldInputClass} auth-password-input`}
                                    type={showConfirmPassword ? 'text' : 'password'}
                                    id="regConfirm"
                                    value={confirmPassword}
                                    onChange={(e) => setConfirmPassword(e.target.value)}
                                    maxLength={100}
                                    required
                                />
                                <button
                                    className="password-toggle"
                                    type="button"
                                    onClick={() => setShowConfirmPassword((current) => !current)}
                                    aria-label={confirmPasswordToggleLabel}
                                    aria-pressed={showConfirmPassword}
                                    title={confirmPasswordToggleLabel}
                                >
                                    {showConfirmPassword ? <EyeOff className="password-toggle__icon" size={18} aria-hidden="true" /> : <Eye className="password-toggle__icon" size={18} aria-hidden="true" />}
                                </button>
                            </div>
                        </div>

                        <div
                            className={cn(
                                'password-strength auth-field-full',
                                `is-score-${passwordStrength.score}`
                            )}
                            aria-live="polite"
                        >
                            <div className="password-strength__header">
                                <span>{t('authModal.passwordStrength.label')}</span>
                                <strong>{t(`authModal.passwordStrength.levels.${passwordStrength.level}`)}</strong>
                            </div>
                            <meter
                                className="password-strength__meter"
                                min={0}
                                max={4}
                                low={2}
                                high={3}
                                optimum={4}
                                value={passwordStrength.score}
                                aria-label={t('authModal.passwordStrength.label')}
                                style={{ accentColor: passwordStrengthColor }}
                            />
                        </div>

                        {shouldUseTurnstile && (
                            <div
                                id="registerTurnstileContainer"
                                ref={registerContainerRef}
                                className="recaptcha-container auth-field-full overflow-x-auto"
                            />
                        )}

                        <button type="submit" className={`${primaryButtonClass} auth-field-full`} disabled={isLoading}>
                            {isLoading ? t('authModal.actions.registerLoading') : t('auth.register')}
                        </button>

                        {(googleAvailable || telegramAvailable) && (
                            <div className="auth-field-full space-y-2 pt-1">
                                {googleAvailable && (
                                    <SocialAuthButton
                                        href={googleHref}
                                        label={t('authModal.actions.registerWithGoogle')}
                                        icon={<GoogleLogo />}
                                    >
                                        {t('authModal.actions.registerWithGoogle')}
                                    </SocialAuthButton>
                                )}
                                {renderTelegramLogin()}
                            </div>
                        )}
                    </form>

                    {!linkMode && (
                        <p className="auth-switch-link text-center text-sm text-muted">
                            {t('authModal.switch.haveAccount')}{' '}
                            <button className="auth-switch-action font-semibold text-[var(--color-text-link)] hover:underline" type="button" onClick={switchView}>
                                {t('auth.login')}
                            </button>
                        </p>
                    )}
                </div>
            )}

            {message && (
                <div
                    className={cn(
                        'auth-message mt-5 rounded-lg border px-4 py-3 text-center text-sm font-semibold',
                        message.type === 'success'
                            ? 'border-[rgba(var(--color-success-raw),0.4)] bg-[rgba(var(--color-success-raw),0.12)] text-success'
                            : 'border-[rgba(var(--color-error-raw),0.35)] bg-[rgba(var(--color-error-raw),0.12)] text-danger'
                    )}
                    role={message.type === 'success' ? 'status' : 'alert'}
                >
                    {message.text}
                </div>
            )}
        </ModalShell>
    );
};

export default AuthModal;
