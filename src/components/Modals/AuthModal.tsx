import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../../context/AuthContext';
import { authService } from '../../services/auth';
import { apiService } from '../../services/api';

const AuthModal = ({ onClose, initialView = 'login' }) => {
    const { login } = useAuth();
    const [isLoginView, setIsLoginView] = useState(initialView === 'login');
    const [isLoading, setIsLoading] = useState(false);
    const [message, setMessage] = useState(null); // { type: 'error' | 'success', text: '' }
    const [authConfig, setAuthConfig] = useState(null);
    const [googleUrl, setGoogleUrl] = useState('/login/google');
    const [googleAvailable, setGoogleAvailable] = useState(false);
    const loginTurnstileIdRef = useRef(undefined);
    const registerTurnstileIdRef = useRef(undefined);
    const loginContainerRef = useRef(null);
    const registerContainerRef = useRef(null);
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
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [username, setUsername] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
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
                if (cancelled) return;
                if (!targetRef.current) return;
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
            } catch (e) {
                console.warn('Failed to get Turnstile response', e);
            }

            const res = await login(email, password, turnstileResponse);
            if (res.success) {
                setMessage({ type: 'success', text: res.message || 'Успешный вход' });
                try {
                    if (window.turnstile && loginTurnstileIdRef.current !== undefined) {
                        window.turnstile.reset(loginTurnstileIdRef.current);
                    }
                } catch (err) {
                }
                setTimeout(() => {
                    onClose();
                }, 1500);
            } else {
                try {
                    if (window.turnstile && loginTurnstileIdRef.current !== undefined) {
                        window.turnstile.reset(loginTurnstileIdRef.current);
                    }
                } catch (err) {
                }
                setMessage({ type: 'error', text: res.error || 'Ошибка входа' });
            }
        } catch (err) {
            setMessage({ type: 'error', text: 'Ошибка сети или сервера' });
        } finally {
            setIsLoading(false);
        }
    };

    const handleRegister = async (e) => {
        e.preventDefault();
        if (password !== confirmPassword) {
            setMessage({ type: 'error', text: 'Пароли не совпадают' });
            return;
        }
        if (username.length > 100) {
            setMessage({ type: 'error', text: 'Имя пользователя не должно превышать 100 символов' });
            return;
        }
        if (email.length > 100) {
            setMessage({ type: 'error', text: 'Email не должен превышать 100 символов' });
            return;
        }
        if (password.length > 100) {
            setMessage({ type: 'error', text: 'Пароль не должен превышать 100 символов' });
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
            } catch (e) {
                console.warn('Failed to get Turnstile response', e);
            }

            const res = await authService.register(username, email, password, turnstileResponse);
            if (res.success) {
                setMessage({ type: 'success', text: 'Регистрация успешна! Проверьте email для подтверждения.' });
                try {
                    if (window.turnstile && registerTurnstileIdRef.current !== undefined) {
                        window.turnstile.reset(registerTurnstileIdRef.current);
                    }
                } catch (err) {
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
                } catch (err) {
                }
                setMessage({ type: 'error', text: res.error || 'Ошибка регистрации' });
            }
        } catch (err) {
            setMessage({ type: 'error', text: 'Ошибка сети или сервера' });
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
        <div className="auth-modal" style={{ display: 'flex' }}>
            <div className="auth-modal-content">
                <button className="auth-modal-close" onClick={onClose} aria-label="Закрыть">×</button>

                {isLoginView ? (

                    <div className="auth-form">
                        <h2>Вход в аккаунт</h2>
                        <form onSubmit={handleLogin}>
                            <div className="form-group">
                                <label htmlFor="loginEmail">Email:</label>
                                <input
                                    type="email"
                                    id="loginEmail"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    required
                                />
                            </div>
                            <div className="form-group">
                                <label htmlFor="loginPassword">Пароль:</label>
                                <input
                                    type="password"
                                    id="loginPassword"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                />
                            </div>

                            {}
                            {authConfig?.turnstile_site_key && (
                                <div id="loginTurnstileContainer" ref={loginContainerRef} style={{ marginBottom: '10px' }}></div>
                            )}

                            <button type="submit" className="btn-primary btn-block" disabled={isLoading}>
                                {isLoading ? 'Вход...' : 'Войти'}
                            </button>

                            {}
                            {googleAvailable && (
                                <div style={{ marginTop: '10px' }}>
                                    <a className="btn btn-google" href={googleUrl}>
                                        <i className="fab fa-google" style={{ marginRight: '8px' }}></i> Войти с Google
                                    </a>
                                </div>
                            )}
                        </form>
                        <p className="auth-switch-link">
                            Нет аккаунта? <a href="#" onClick={switchView}>Зарегистрируйтесь</a>
                        </p>
                    </div>
                ) : (

                    <div className="auth-form">
                        <h2>Регистрация</h2>
                        <form onSubmit={handleRegister}>
                            <div className="form-group">
                                <label htmlFor="regUsername">Имя пользователя:</label>
                                <input
                                    type="text"
                                    id="regUsername"
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                    maxLength="100"
                                    required
                                />
                            </div>
                            <div className="form-group">
                                <label htmlFor="regEmail">Email:</label>
                                <input
                                    type="email"
                                    id="regEmail"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    maxLength="100"
                                    required
                                />
                            </div>
                            <div className="form-group">
                                <label htmlFor="regPassword">Пароль:</label>
                                <input
                                    type="password"
                                    id="regPassword"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    minLength="8"
                                    maxLength="100"
                                    required
                                />
                            </div>
                            <div className="form-group">
                                <label htmlFor="regConfirm">Повторите пароль:</label>
                                <input
                                    type="password"
                                    id="regConfirm"
                                    value={confirmPassword}
                                    onChange={(e) => setConfirmPassword(e.target.value)}
                                    maxLength="100"
                                    required
                                />
                            </div>

                            {}
                            {authConfig?.turnstile_site_key && (
                                <div id="registerTurnstileContainer" ref={registerContainerRef} style={{ marginBottom: '10px' }}></div>
                            )}

                            <button type="submit" className="btn-primary btn-block" disabled={isLoading}>
                                {isLoading ? 'Регистрация...' : 'Зарегистрироваться'}
                            </button>

                            {}
                            {googleAvailable && (
                                <div style={{ marginTop: '10px' }}>
                                    <a className="btn btn-google" href={googleUrl}>
                                        <i className="fab fa-google" style={{ marginRight: '8px' }}></i> Регистрация с Google
                                    </a>
                                </div>
                            )}
                        </form>
                        <p className="auth-switch-link">
                            Уже есть аккаунт? <a href="#" onClick={switchView}>Войдите</a>
                        </p>
                    </div>
                )}

                {message && (
                    <div className={`auth-message ${message.type}`} style={{ display: 'block' }}>
                        {message.text}
                    </div>
                )}
            </div>
        </div>
    );
};

export default AuthModal;
