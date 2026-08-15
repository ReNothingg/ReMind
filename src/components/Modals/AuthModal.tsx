import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, X } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { authService } from '../../services/auth';
import { apiService } from '../../services/api';
import { loadTelegramLoginSdk } from '../../services/telegramLogin';
import SocialAuthButton, { AppleLogo, GoogleLogo, TelegramLogo } from '../Auth/SocialAuthButton';
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
    const [appleUrl, setAppleUrl] = useState('/login/apple');
    const [appleAvailable, setAppleAvailable] = useState(false);
    const [telegramSdkReady, setTelegramSdkReady] = useState(false);
    const [telegramLoading, setTelegramLoading] = useState(false);
    const [telegramLink, setTelegramLink] = useState<{ url: string; request_id: string } | null>(null);
    const [telegramLinkWaiting, setTelegramLinkWaiting] = useState(false);
    const loginTurnstileIdRef = useRef(undefined);
    const registerTurnstileIdRef = useRef(undefined);
    const authConfigRequestStartedRef = useRef(false);
    const loginContainerRef = useRef(null);
    const registerContainerRef = useRef(null);
    const registerNameRef = useRef<HTMLInputElement | null>(null);
    const registerUsernameRef = useRef<HTMLInputElement | null>(null);
    const registerEmailRef = useRef<HTMLInputElement | null>(null);
    const registerPasswordRef = useRef<HTMLInputElement | null>(null);
    const registerConfirmPasswordRef = useRef<HTMLInputElement | null>(null);
    const usernameAutofillAppliedRef = useRef(false);
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
    const telegramBotLinkAvailable = Boolean(authConfig?.telegram_bot_link_available);
    const authTitleKey = linkMode
        ? 'authModal.telegramLinkTitle'
        : isLoginView
            ? 'authModal.loginTitle'
            : 'authModal.registerTitle';
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
    const appleHref = (() => {
        try {
            const base = new URL(appleUrl, window.location.origin);
            base.searchParams.set('redirect_to', window.location.href);
            return base.toString();
        } catch {
            return '';
        }
    })();

    useEffect(() => {
        setIsLoginView(initialView === 'login' || linkMode);
    }, [initialView, linkMode]);

    // Keep the convenience fields in sync after the browser/password manager
    // has supplied a value. Do not poll the DOM: polling controlled inputs can
    // close Safari's native autofill popover while it is being shown.
    useEffect(() => {
        if (isLoginView || linkMode) return;
        if (!username && email && !usernameAutofillAppliedRef.current) {
            const localPart = email.split('@')[0]
                .replace(/[^a-zA-Z0-9_-]/g, '')
                .replace(/^[_-]+/, '')
                .slice(0, 50);
            if (localPart.length >= 3) {
                usernameAutofillAppliedRef.current = true;
                if (registerUsernameRef.current) {
                    registerUsernameRef.current.value = localPart;
                }
                setUsername(localPart);
            }
        }
    }, [email, isLoginView, linkMode, username]);

    useEffect(() => {
        if (!isLoginView && !linkMode && password && !confirmPassword) {
            if (registerConfirmPasswordRef.current && !registerConfirmPasswordRef.current.value) {
                registerConfirmPasswordRef.current.value = password;
            }
            setConfirmPassword(password);
        }
    }, [confirmPassword, isLoginView, linkMode, password]);

    useEffect(() => {
        const code = window.sessionStorage.getItem('remind.auth.error');
        if (!code) return;
        window.sessionStorage.removeItem('remind.auth.error');
        const key = code === 'email_in_use'
            ? 'authModal.messages.appleEmailInUse'
            : 'authModal.messages.appleFailed';
        setMessage({ type: 'error', text: t(key) });
    }, [t]);

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
                if (!resp.ok) throw new Error(`Auth config request failed (${resp.status})`);
                const cfg = await resp.json();
                setAuthConfig(cfg);
                setGoogleUrl(cfg.google_login_url || '/login/google');
                setGoogleAvailable(cfg.gauth_available || false);
                setAppleUrl(cfg.apple_login_url || '/login/apple');
                setAppleAvailable(Boolean(cfg.apple_web_available && cfg.apple_login_url));
            } catch (err) {
                console.warn('Failed to load auth config', err);
                if (linkMode) {
                    setMessage({ type: 'error', text: t('authModal.telegramLink.unavailable') });
                }
            }
        };
        loadAuthConfig();
    }, [linkMode, t]);

    useEffect(() => {
        if (linkMode) return;
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
    }, [linkMode, telegramAvailable, t]);

    const prepareTelegramLink = async () => {
        if (!isAuthenticated || telegramLoading) return;
        setTelegramLoading(true);
        setTelegramLink(null);
        setTelegramLinkWaiting(false);
        setMessage(null);
        try {
            const result = await authService.createTelegramLink();
            setTelegramLink(result);
        } catch (error) {
            console.warn('Telegram bot link creation failed', error);
            setMessage({
                type: 'error',
                text: t('authModal.telegramLink.failed'),
            });
        } finally {
            setTelegramLoading(false);
        }
    };

    useEffect(() => {
        if (!linkMode || !telegramBotLinkAvailable || !isAuthenticated || telegramLink || telegramLoading) {
            return;
        }
        void prepareTelegramLink();
        // The request is intentionally issued once when bot-link configuration becomes available.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [linkMode, telegramBotLinkAvailable, isAuthenticated]);

    useEffect(() => {
        if (!linkMode || !telegramLink?.request_id) return;
        let cancelled = false;
        let checking = false;
        let closeTimeout: ReturnType<typeof setTimeout> | undefined;

        const checkStatus = async () => {
            if (checking || cancelled) return;
            checking = true;
            try {
                const result = await authService.getTelegramLinkStatus(telegramLink.request_id);
                if (cancelled || result.status === 'pending') return;
                if (result.status === 'expired') {
                    setTelegramLink(null);
                    setTelegramLinkWaiting(false);
                    setMessage({ type: 'error', text: t('authModal.telegramLink.expired') });
                    return;
                }
                if (result.status === 'failed') {
                    setTelegramLink(null);
                    setTelegramLinkWaiting(false);
                    setMessage({
                        type: 'error',
                        text: t(result.code === 'identity_in_use'
                            ? 'settings.account.loginMethods.identityInUse'
                            : 'authModal.telegramLink.failed'),
                    });
                    return;
                }
                const authState = await checkAuth();
                if (cancelled) return;
                if (!authState.authenticated) {
                    setMessage({
                        type: 'error',
                        text: t('settings.account.loginMethods.authRequired'),
                    });
                    return;
                }
                setMessage({ type: 'success', text: t('authModal.telegramLink.success') });
                closeTimeout = setTimeout(onClose, 1200);
            } catch (error) {
                if (!cancelled) console.warn('Telegram bot link status check failed', error);
            } finally {
                checking = false;
            }
        };

        void checkStatus();
        const interval = window.setInterval(checkStatus, 2000);
        return () => {
            cancelled = true;
            window.clearInterval(interval);
            if (closeTimeout) clearTimeout(closeTimeout);
        };
    }, [checkAuth, linkMode, onClose, t, telegramLink?.request_id]);

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

                        const response = await loginWithTelegram(result.id_token);
                        if (!response.success) {
                            setMessage({ type: 'error', text: t('authModal.messages.telegramError') });
                            return;
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
        if (linkMode) {
            if (!telegramBotLinkAvailable && authConfig) {
                return (
                    <div className="auth-message error" role="alert">
                        {t('authModal.telegramLink.unavailable')}
                    </div>
                );
            }
            const labelKey = telegramLinkWaiting
                ? 'authModal.telegramLink.waiting'
                : telegramLink
                    ? 'authModal.telegramLink.openTelegram'
                    : message?.type === 'error'
                        ? 'authModal.telegramLink.retry'
                        : 'authModal.telegramLink.preparing';
            return (
                <div className="space-y-3">
                    <SocialAuthButton
                        href={telegramLink?.url}
                        onClick={telegramLink
                            ? () => setTelegramLinkWaiting(true)
                            : () => void prepareTelegramLink()}
                        newWindow
                        disabled={telegramLoading || (!telegramLink && message?.type !== 'error')}
                        busy={telegramLoading}
                        label={t(labelKey)}
                        icon={<TelegramLogo />}
                    >
                        {t(labelKey)}
                    </SocialAuthButton>
                    {telegramLink && (
                        <p className="text-center text-xs leading-5 text-muted" aria-live="polite">
                            {t(telegramLinkWaiting
                                ? 'authModal.telegramLink.waitingHint'
                                : 'authModal.telegramLink.privateHint')}
                        </p>
                    )}
                </div>
            );
        }
        if (!telegramAvailable) return null;
        const labelKey = isLoginView
                ? 'authModal.actions.loginWithTelegram'
                : 'authModal.actions.registerWithTelegram';
        const loadingKey = 'authModal.actions.telegramLoading';

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

        // Safari may update the DOM value without notifying React. Read the
        // registered controls once on submit so autofilled values are never
        // lost during validation or the request.
        const effectiveName = registerNameRef.current?.value || name;
        const effectiveUsername = registerUsernameRef.current?.value || username;
        const effectiveEmail = registerEmailRef.current?.value || email;
        const effectivePassword = registerPasswordRef.current?.value || password;
        const effectiveConfirmPassword = registerConfirmPasswordRef.current?.value || confirmPassword || effectivePassword;

        const nextFieldErrors: AccountFieldErrors = {};
        const nameError = validateAccountName(effectiveName, t, { required: true });
        const usernameError = validateUsername(effectiveUsername, t);

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

        if (effectivePassword !== effectiveConfirmPassword) {
            setMessage({ type: 'error', text: t('authModal.messages.passwordsMismatch') });
            return;
        }
        if (effectiveName.length > 100) {
            setMessage({ type: 'error', text: t('settings.account.validation.nameLength') });
            return;
        }
        if (effectiveUsername.length > 100) {
            setMessage({ type: 'error', text: t('authModal.messages.usernameTooLong') });
            return;
        }
        if (effectiveEmail.length > 100) {
            setMessage({ type: 'error', text: t('authModal.messages.emailTooLong') });
            return;
        }
        if (effectivePassword.length > 100) {
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

            const res = await authService.register(effectiveName.trim(), effectiveUsername.trim(), effectiveEmail, effectivePassword, turnstileResponse);
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
        usernameAutofillAppliedRef.current = false;
        setConfirmPassword('');
        setShowPassword(false);
        setShowConfirmPassword(false);
    };

    return (
        <ModalShell
            ariaLabel={t(authTitleKey)}
            className="auth-modal items-end px-0 py-0 sm:items-center sm:px-4 sm:py-6"
            contentClassName={cn(
                'auth-modal-content mx-auto w-full rounded-t-xl border-border bg-surface px-5 pb-6 pt-5 text-foreground sm:rounded-xl sm:px-6 sm:pb-6 sm:pt-6',
                linkMode ? 'max-w-[420px]' : 'max-w-[460px]'
            )}
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

            {linkMode ? (
                <div className="auth-form space-y-5">
                    <div className="space-y-2 pr-12">
                        <h2 className="text-[1.45rem] font-bold tracking-normal text-foreground">
                            {t('authModal.telegramLinkTitle')}
                        </h2>
                        <p className="text-sm leading-6 text-muted">
                            {t('authModal.telegramLinkDescription')}
                        </p>
                    </div>

                    {renderTelegramLogin()}
                </div>
            ) : isLoginView ? (
                <div className="auth-form space-y-4">
                    <div className="space-y-1 pr-12">
                        <h2 className="text-[1.45rem] font-bold tracking-normal text-foreground">
                            {t('authModal.loginTitle')}
                        </h2>
                    </div>

                    <form className="space-y-4" onSubmit={handleLogin} autoComplete="on">
                        <div className="form-group flex flex-col gap-1.5">
                            <label className={fieldLabelClass} htmlFor="loginEmail">{t('authModal.fields.email')}</label>
                            <input
                                className={fieldInputClass}
                                type="email"
                                id="loginEmail"
                                name="email"
                                autoComplete="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                            />
                        </div>
                        <div className="form-group flex flex-col gap-1.5">
                            <div className="password-label-row">
                                <label className={fieldLabelClass} htmlFor="loginPassword">{t('authModal.fields.password')}</label>
                                <button
                                    className="password-toggle password-toggle--label"
                                    type="button"
                                    onClick={() => setShowPassword((current) => !current)}
                                    aria-label={passwordToggleLabel}
                                    aria-pressed={showPassword}
                                    title={passwordToggleLabel}
                                >
                                    {showPassword ? <EyeOff className="password-toggle__icon" size={18} aria-hidden="true" /> : <Eye className="password-toggle__icon" size={18} aria-hidden="true" />}
                                </button>
                            </div>
                            <div className="password-field">
                                <input
                                    className={`${fieldInputClass} auth-password-input`}
                                    type={showPassword ? 'text' : 'password'}
                                    id="loginPassword"
                                    name="password"
                                    autoComplete="current-password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                />
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

                        {(appleAvailable || googleAvailable || telegramAvailable) && (
                            <div className="space-y-2 pt-1">
                                {appleAvailable && appleHref && (
                                    <SocialAuthButton
                                        href={appleHref}
                                        label={t('authModal.actions.loginWithApple')}
                                        icon={<AppleLogo />}
                                    >
                                        {t('authModal.actions.loginWithApple')}
                                    </SocialAuthButton>
                                )}
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

                    <form className="auth-register-form" onSubmit={handleRegister} autoComplete="on">
                        <div className="form-group flex flex-col gap-1.5">
                            <label className={fieldLabelClass} htmlFor="name">{t('authModal.fields.name')}</label>
                            <input
                                className={fieldInputClass}
                                type="text"
                                id="name"
                                name="given-name"
                                autoComplete="given-name"
                                autoCapitalize="words"
                                ref={registerNameRef}
                                defaultValue={name}
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
                            <label className={fieldLabelClass} htmlFor="username">{t('authModal.fields.username')}</label>
                            <input
                                className={fieldInputClass}
                                type="text"
                                id="username"
                                name="username"
                                autoComplete="username"
                                ref={registerUsernameRef}
                                defaultValue={username}
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
                            <label className={fieldLabelClass} htmlFor="email">{t('authModal.fields.email')}</label>
                            <input
                                className={fieldInputClass}
                                type="email"
                                id="email"
                                name="email"
                                autoComplete="email"
                                ref={registerEmailRef}
                                defaultValue={email}
                                onChange={(e) => setEmail(e.target.value)}
                                maxLength={100}
                                required
                            />
                        </div>
                        <div className="form-group flex flex-col gap-1.5">
                            <div className="password-label-row">
                                <label className={fieldLabelClass} htmlFor="new-password">{t('authModal.fields.password')}</label>
                                <button
                                    className="password-toggle password-toggle--label"
                                    type="button"
                                    onClick={() => setShowPassword((current) => !current)}
                                    aria-label={passwordToggleLabel}
                                    aria-pressed={showPassword}
                                    title={passwordToggleLabel}
                                >
                                    {showPassword ? <EyeOff className="password-toggle__icon" size={18} aria-hidden="true" /> : <Eye className="password-toggle__icon" size={18} aria-hidden="true" />}
                                </button>
                            </div>
                            <div className="password-field">
                                <input
                                    className={`${fieldInputClass} auth-password-input`}
                                    type={showPassword ? 'text' : 'password'}
                                    id="new-password"
                                    name="new-password"
                                    autoComplete="new-password"
                                    ref={registerPasswordRef}
                                    defaultValue={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    minLength={8}
                                    maxLength={100}
                                    required
                                />
                            </div>
                        </div>
                        <div className="form-group flex flex-col gap-1.5">
                            <div className="password-label-row">
                                <label className={fieldLabelClass} htmlFor="confirm-password">{t('authModal.fields.confirmPassword')}</label>
                                <button
                                    className="password-toggle password-toggle--label"
                                    type="button"
                                    onClick={() => setShowConfirmPassword((current) => !current)}
                                    aria-label={confirmPasswordToggleLabel}
                                    aria-pressed={showConfirmPassword}
                                    title={confirmPasswordToggleLabel}
                                >
                                    {showConfirmPassword ? <EyeOff className="password-toggle__icon" size={18} aria-hidden="true" /> : <Eye className="password-toggle__icon" size={18} aria-hidden="true" />}
                                </button>
                            </div>
                            <div className="password-field">
                                <input
                                    className={`${fieldInputClass} auth-password-input`}
                                    type={showConfirmPassword ? 'text' : 'password'}
                                    id="confirm-password"
                                    name="confirm-password"
                                    autoComplete="new-password"
                                    ref={registerConfirmPasswordRef}
                                    defaultValue={confirmPassword}
                                    onChange={(e) => setConfirmPassword(e.target.value)}
                                    maxLength={100}
                                    required
                                />
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

                        {(appleAvailable || googleAvailable || telegramAvailable) && (
                            <div className="auth-field-full space-y-2 pt-1">
                                {appleAvailable && appleHref && (
                                    <SocialAuthButton
                                        href={appleHref}
                                        label={t('authModal.actions.registerWithApple')}
                                        icon={<AppleLogo />}
                                    >
                                        {t('authModal.actions.registerWithApple')}
                                    </SocialAuthButton>
                                )}
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
