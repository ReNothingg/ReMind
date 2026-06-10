import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { authService } from '../../services/auth';
import { apiService } from '../../services/api';
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

const getPasswordStrength = (value: string) => {
    if (!value) {
        return { score: 0, level: 'empty' };
    }

    let score = 0;
    const hasLower = /[a-z]/.test(value);
    const hasUpper = /[A-Z]/.test(value);
    const hasNumber = /\d/.test(value);
    const hasSymbol = /[^A-Za-z0-9]/.test(value);
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

const AuthModal = ({ onClose, initialView = 'login' }) => {
    const { t } = useTranslation();
    const { login } = useAuth();
    const [isLoginView, setIsLoginView] = useState(initialView === 'login');
    const [isLoading, setIsLoading] = useState(false);
    const [message, setMessage] = useState(null);
    const [authConfig, setAuthConfig] = useState(null);
    const [googleUrl, setGoogleUrl] = useState('/login/google');
    const [googleAvailable, setGoogleAvailable] = useState(false);
    const loginTurnstileIdRef = useRef(undefined);
    const registerTurnstileIdRef = useRef(undefined);
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
    const fieldInputClass = 'ui-input min-h-10 rounded-xl bg-interactive px-4 py-2.5 text-[0.94rem]';
    const primaryButtonClass = 'btn-primary btn-block ui-button-primary min-h-10 w-full justify-center rounded-xl px-4 py-2.5 text-[0.94rem] font-semibold';
    const secondaryAuthButtonClass = 'btn btn-google flex min-h-10 w-full items-center justify-center gap-2 rounded-xl border border-border-strong bg-surface px-4 py-2.5 text-[0.94rem] font-medium text-foreground transition duration-200 ease-out hover:border-border-heavy hover:bg-interactive';
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
        const handleEscapeKey = (event) => {
            if (event.key === 'Escape') {
                onClose();
            }
        };

        document.addEventListener('keydown', handleEscapeKey);
        return () => document.removeEventListener('keydown', handleEscapeKey);
    }, [onClose]);

    useEffect(() => {
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
            if (cancelled || !loaded || !window.turnstile) return;
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
    }, [authConfig, isLoginView, shouldUseTurnstile]);

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
            className="auth-modal items-end px-0 py-0 sm:items-center sm:px-4 sm:py-6"
            contentClassName="auth-modal-content mx-auto w-full max-w-[460px] rounded-t-[20px] border-border bg-surface px-5 pb-6 pt-5 text-foreground shadow-[var(--shadow-xl)] sm:rounded-2xl sm:px-6 sm:pb-6 sm:pt-6"
            onBackdropClick={onClose}
        >
            <button
                className="auth-modal-close ui-icon-control absolute right-4 top-4 size-10 rounded-xl border-transparent bg-interactive text-muted hover:bg-surface-alt hover:text-foreground"
                onClick={onClose}
                aria-label={t('translationPanel.close')}
                type="button"
            >
                x
            </button>

            {isLoginView ? (
                <div className="auth-form space-y-4">
                    <div className="space-y-1 pr-12">
                        <h2 className="text-[1.45rem] font-bold tracking-[-0.01em] text-foreground">
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

                        {googleAvailable && (
                            <div className="pt-1">
                                <a className={secondaryAuthButtonClass} href={googleHref}>
                                    <i className="fab fa-google text-[18px] text-[#ea4335]" />
                                    <span>{t('authModal.actions.loginWithGoogle')}</span>
                                </a>
                            </div>
                        )}
                    </form>

                    <p className="auth-switch-link text-center text-sm text-muted">
                        {t('authModal.switch.noAccount')}{' '}
                        <a className="font-semibold text-[var(--color-text-link)] hover:underline" href="#" onClick={switchView}>
                            {t('auth.register')}
                        </a>
                    </p>
                </div>
            ) : (
                <div className="auth-form auth-register-panel space-y-4">
                    <div className="space-y-1 pr-12">
                        <h2 className="text-[1.45rem] font-bold tracking-[-0.01em] text-foreground">
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
                            />
                            {fieldErrors.name && (
                                <p className="text-sm font-medium text-danger">{fieldErrors.name}</p>
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
                            />
                            {fieldErrors.username && (
                                <p className="text-sm font-medium text-danger">{fieldErrors.username}</p>
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

                        {googleAvailable && (
                            <div className="auth-field-full pt-1">
                                <a className={secondaryAuthButtonClass} href={googleHref}>
                                    <i className="fab fa-google text-[18px] text-[#ea4335]" />
                                    <span>{t('authModal.actions.registerWithGoogle')}</span>
                                </a>
                            </div>
                        )}
                    </form>

                    <p className="auth-switch-link text-center text-sm text-muted">
                        {t('authModal.switch.haveAccount')}{' '}
                        <a className="font-semibold text-[var(--color-text-link)] hover:underline" href="#" onClick={switchView}>
                            {t('auth.login')}
                        </a>
                    </p>
                </div>
            )}

            {message && (
                <div
                    className={cn(
                        'auth-message mt-5 rounded-xl border px-4 py-3 text-center text-sm font-semibold',
                        message.type === 'success'
                            ? 'border-[rgba(var(--color-success-raw),0.4)] bg-[rgba(var(--color-success-raw),0.12)] text-success'
                            : 'border-[rgba(var(--color-error-raw),0.35)] bg-[rgba(var(--color-error-raw),0.12)] text-danger'
                    )}
                >
                    {message.text}
                </div>
            )}
        </ModalShell>
    );
};

export default AuthModal;
