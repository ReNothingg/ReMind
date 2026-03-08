import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../../context/AuthContext';
import { authService } from '../../services/auth';
import { apiService } from '../../services/api';
import ModalShell from '../UI/ModalShell';
import { cn } from '../../utils/cn';

const AuthModal = ({ onClose, initialView = 'login' }) => {
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
    const [username, setUsername] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');

    const fieldLabelClass = 'ui-field-label';
    const fieldInputClass = 'ui-input min-h-11 rounded-xl bg-interactive px-4 py-3 text-[0.95rem]';
    const primaryButtonClass = 'btn-primary btn-block ui-button-primary min-h-11 w-full justify-center rounded-xl px-4 py-3 text-[0.95rem] font-semibold';
    const secondaryAuthButtonClass = 'btn btn-google flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-border-strong bg-surface px-4 py-3 text-[0.95rem] font-medium text-foreground transition duration-200 ease-out hover:border-border-heavy hover:bg-interactive';

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
        } catch (_err) {
            const separator = googleUrl.includes('?') ? '&' : '?';
            return `${googleUrl}${separator}redirect_to=${encodeURIComponent(window.location.href)}`;
        }
    })();

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
                console.log('Turnstile script loaded successfully');
                return true;
            }
            await new Promise(resolve => setTimeout(resolve, delayMs));
        }
        console.warn(`Turnstile script failed to load after ${maxRetries * delayMs}ms`);
        return false;
    };

    useEffect(() => {
        if (!authConfig?.turnstile_site_key) return;
        let timeoutId;
        let cancelled = false;

        const initTurnstile = async () => {
            const loaded = await waitForTurnstile();
            if (cancelled || !loaded || !window.turnstile) return;
            const targetRef = isLoginView ? loginContainerRef : registerContainerRef;
            const idRef = isLoginView ? loginTurnstileIdRef : registerTurnstileIdRef;
            timeoutId = setTimeout(() => {
                if (cancelled || !targetRef.current) return;
                removeTurnstile(idRef, targetRef);
                if (isLoginView) {
                    console.log('Rendering login Turnstile widget');
                } else {
                    console.log('Rendering register Turnstile widget');
                }
                try {
                    idRef.current = window.turnstile.render(targetRef.current, {
                        sitekey: authConfig.turnstile_site_key,
                        theme: 'dark',
                        callback: () => {
                            if (isLoginView) {
                                console.log('Turnstile challenge solved (login)');
                            } else {
                                console.log('Turnstile challenge solved (register)');
                            }
                        },
                        'error-callback': () => {
                            if (isLoginView) {
                                console.error('Turnstile error (login)');
                            } else {
                                console.error('Turnstile error (register)');
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
            }, 100);
        };

        initTurnstile();
        return () => {
            cancelled = true;
            if (timeoutId !== undefined) clearTimeout(timeoutId);
        };
    }, [authConfig, isLoginView]);

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

        try {
            let turnstileResponse = null;
            try {
                if (window.turnstile && loginTurnstileIdRef.current !== undefined) {
                    turnstileResponse = window.turnstile.getResponse(loginTurnstileIdRef.current);
                }
            } catch (error) {
                console.warn('Failed to get Turnstile response', error);
            }

            const res = await login(email, password, turnstileResponse);
            if (res.success) {
                setMessage({ type: 'success', text: res.message || 'РЈСЃРїРµС€РЅС‹Р№ РІС…РѕРґ' });
                try {
                    if (window.turnstile && loginTurnstileIdRef.current !== undefined) {
                        window.turnstile.reset(loginTurnstileIdRef.current);
                    }
                } catch (_err) {
                }
                setTimeout(() => {
                    onClose();
                }, 1500);
            } else {
                try {
                    if (window.turnstile && loginTurnstileIdRef.current !== undefined) {
                        window.turnstile.reset(loginTurnstileIdRef.current);
                    }
                } catch (_err) {
                }
                setMessage({ type: 'error', text: res.error || 'РћС€РёР±РєР° РІС…РѕРґР°' });
            }
        } catch (_err) {
            setMessage({ type: 'error', text: 'РћС€РёР±РєР° СЃРµС‚Рё РёР»Рё СЃРµСЂРІРµСЂР°' });
        } finally {
            setIsLoading(false);
        }
    };

    const handleRegister = async (e) => {
        e.preventDefault();
        if (password !== confirmPassword) {
            setMessage({ type: 'error', text: 'РџР°СЂРѕР»Рё РЅРµ СЃРѕРІРїР°РґР°СЋС‚' });
            return;
        }
        if (username.length > 100) {
            setMessage({ type: 'error', text: 'РРјСЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ РЅРµ РґРѕР»Р¶РЅРѕ РїСЂРµРІС‹С€Р°С‚СЊ 100 СЃРёРјРІРѕР»РѕРІ' });
            return;
        }
        if (email.length > 100) {
            setMessage({ type: 'error', text: 'Email РЅРµ РґРѕР»Р¶РµРЅ РїСЂРµРІС‹С€Р°С‚СЊ 100 СЃРёРјРІРѕР»РѕРІ' });
            return;
        }
        if (password.length > 100) {
            setMessage({ type: 'error', text: 'РџР°СЂРѕР»СЊ РЅРµ РґРѕР»Р¶РµРЅ РїСЂРµРІС‹С€Р°С‚СЊ 100 СЃРёРјРІРѕР»РѕРІ' });
            return;
        }

        setIsLoading(true);
        setMessage(null);

        try {
            let turnstileResponse = null;
            try {
                if (window.turnstile && registerTurnstileIdRef.current !== undefined) {
                    turnstileResponse = window.turnstile.getResponse(registerTurnstileIdRef.current);
                }
            } catch (error) {
                console.warn('Failed to get Turnstile response', error);
            }

            const res = await authService.register(username, email, password, turnstileResponse);
            if (res.success) {
                setMessage({ type: 'success', text: 'Р РµРіРёСЃС‚СЂР°С†РёСЏ СѓСЃРїРµС€РЅР°! РџСЂРѕРІРµСЂСЊС‚Рµ email РґР»СЏ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ.' });
                try {
                    if (window.turnstile && registerTurnstileIdRef.current !== undefined) {
                        window.turnstile.reset(registerTurnstileIdRef.current);
                    }
                } catch (_err) {
                }
                setTimeout(() => {
                    setIsLoginView(true);
                    setMessage(null);
                }, 2000);
            } else {
                try {
                    if (window.turnstile && registerTurnstileIdRef.current !== undefined) {
                        window.turnstile.reset(registerTurnstileIdRef.current);
                    }
                } catch (_err) {
                }
                setMessage({ type: 'error', text: res.error || 'РћС€РёР±РєР° СЂРµРіРёСЃС‚СЂР°С†РёРё' });
            }
        } catch (_err) {
            setMessage({ type: 'error', text: 'РћС€РёР±РєР° СЃРµС‚Рё РёР»Рё СЃРµСЂРІРµСЂР°' });
        } finally {
            setIsLoading(false);
        }
    };

    const switchView = (e) => {
        e.preventDefault();
        setIsLoginView(!isLoginView);
        setMessage(null);
        setEmail('');
        setPassword('');
        setUsername('');
        setConfirmPassword('');
    };

    return (
        <ModalShell
            className="auth-modal items-end px-0 py-0 sm:items-center sm:px-4 sm:py-6"
            contentClassName="auth-modal-content mx-auto w-full max-w-[420px] rounded-t-[20px] border-border bg-surface px-6 pb-8 pt-6 text-foreground shadow-[var(--shadow-xl)] sm:rounded-2xl sm:px-8 sm:pb-8 sm:pt-8"
        >
            <button
                className="auth-modal-close ui-icon-control absolute right-4 top-4 size-10 rounded-xl border-transparent bg-interactive text-muted hover:bg-surface-alt hover:text-foreground"
                onClick={onClose}
                aria-label="Р—Р°РєСЂС‹С‚СЊ"
                type="button"
            >
                Г—
            </button>

            {isLoginView ? (
                <div className="auth-form space-y-5 pr-6 sm:pr-8">
                    <div className="space-y-1">
                        <h2 className="text-[1.45rem] font-bold tracking-[-0.01em] text-foreground">
                            Р’С…РѕРґ РІ Р°РєРєР°СѓРЅС‚
                        </h2>
                    </div>

                    <form className="space-y-4" onSubmit={handleLogin}>
                        <div className="form-group flex flex-col gap-1.5">
                            <label className={fieldLabelClass} htmlFor="loginEmail">Email:</label>
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
                            <label className={fieldLabelClass} htmlFor="loginPassword">РџР°СЂРѕР»СЊ:</label>
                            <input
                                className={fieldInputClass}
                                type="password"
                                id="loginPassword"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                            />
                        </div>

                        {authConfig?.turnstile_site_key && (
                            <div
                                id="loginTurnstileContainer"
                                ref={loginContainerRef}
                                className="overflow-x-auto"
                            />
                        )}

                        <button type="submit" className={primaryButtonClass} disabled={isLoading}>
                            {isLoading ? 'Р’С…РѕРґ...' : 'Р’РѕР№С‚Рё'}
                        </button>

                        {googleAvailable && (
                            <div className="pt-1">
                                <a className={secondaryAuthButtonClass} href={googleHref}>
                                    <i className="fab fa-google text-[18px] text-[#ea4335]" />
                                    <span>Р’РѕР№С‚Рё СЃ Google</span>
                                </a>
                            </div>
                        )}
                    </form>

                    <p className="auth-switch-link text-center text-sm text-muted">
                        РќРµС‚ Р°РєРєР°СѓРЅС‚Р°?{' '}
                        <a className="font-semibold text-[var(--color-text-link)] hover:underline" href="#" onClick={switchView}>
                            Р—Р°СЂРµРіРёСЃС‚СЂРёСЂСѓР№С‚РµСЃСЊ
                        </a>
                    </p>
                </div>
            ) : (
                <div className="auth-form space-y-5 pr-6 sm:pr-8">
                    <div className="space-y-1">
                        <h2 className="text-[1.45rem] font-bold tracking-[-0.01em] text-foreground">
                            Р РµРіРёСЃС‚СЂР°С†РёСЏ
                        </h2>
                    </div>

                    <form className="space-y-4" onSubmit={handleRegister}>
                        <div className="form-group flex flex-col gap-1.5">
                            <label className={fieldLabelClass} htmlFor="regUsername">РРјСЏ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ:</label>
                            <input
                                className={fieldInputClass}
                                type="text"
                                id="regUsername"
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                maxLength="100"
                                required
                            />
                        </div>
                        <div className="form-group flex flex-col gap-1.5">
                            <label className={fieldLabelClass} htmlFor="regEmail">Email:</label>
                            <input
                                className={fieldInputClass}
                                type="email"
                                id="regEmail"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                maxLength="100"
                                required
                            />
                        </div>
                        <div className="form-group flex flex-col gap-1.5">
                            <label className={fieldLabelClass} htmlFor="regPassword">РџР°СЂРѕР»СЊ:</label>
                            <input
                                className={fieldInputClass}
                                type="password"
                                id="regPassword"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                minLength="8"
                                maxLength="100"
                                required
                            />
                        </div>
                        <div className="form-group flex flex-col gap-1.5">
                            <label className={fieldLabelClass} htmlFor="regConfirm">РџРѕРІС‚РѕСЂРёС‚Рµ РїР°СЂРѕР»СЊ:</label>
                            <input
                                className={fieldInputClass}
                                type="password"
                                id="regConfirm"
                                value={confirmPassword}
                                onChange={(e) => setConfirmPassword(e.target.value)}
                                maxLength="100"
                                required
                            />
                        </div>

                        {authConfig?.turnstile_site_key && (
                            <div
                                id="registerTurnstileContainer"
                                ref={registerContainerRef}
                                className="overflow-x-auto"
                            />
                        )}

                        <button type="submit" className={primaryButtonClass} disabled={isLoading}>
                            {isLoading ? 'Р РµРіРёСЃС‚СЂР°С†РёСЏ...' : 'Р—Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°С‚СЊСЃСЏ'}
                        </button>

                        {googleAvailable && (
                            <div className="pt-1">
                                <a className={secondaryAuthButtonClass} href={googleHref}>
                                    <i className="fab fa-google text-[18px] text-[#ea4335]" />
                                    <span>Р РµРіРёСЃС‚СЂР°С†РёСЏ СЃ Google</span>
                                </a>
                            </div>
                        )}
                    </form>

                    <p className="auth-switch-link text-center text-sm text-muted">
                        РЈР¶Рµ РµСЃС‚СЊ Р°РєРєР°СѓРЅС‚?{' '}
                        <a className="font-semibold text-[var(--color-text-link)] hover:underline" href="#" onClick={switchView}>
                            Р’РѕР№РґРёС‚Рµ
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
