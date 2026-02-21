import React, { useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';


export const GuestModeManager = ({ children }) => {
    const { isAuthenticated } = useAuth();

    useEffect(() => {
        if (!isAuthenticated) {
            document.body.classList.add('guest-mode');
        } else {
            document.body.classList.remove('guest-mode');
        }
        return () => {
            document.body.classList.remove('guest-mode');
        };
    }, [isAuthenticated]);

    if (isAuthenticated) {
        return <>{children}</>;
    }

    return <>{children}</>;
};


export const GuestButtons = ({ onOpenAuth, onShowRegister }) => {
    return (
        <div className="guest-auth-buttons" id="guestAuthButtons">
            <button className="guest-btn guest-login-btn" onClick={() => {
                if (onOpenAuth) onOpenAuth();
            }} aria-label="Войти в систему">
                Войти
            </button>
            <button className="guest-btn guest-register-btn" onClick={() => {
                if (onShowRegister) onShowRegister();
            }} aria-label="Зарегистрироваться">
                Зарегистрироваться бесплатно
            </button>
        </div>
    );
};


export const GuestModal = ({ isOpen, onClose, onOpenAuth, onShowRegister }) => {
    if (!isOpen) return null;

    return (
        <>
            <div className="guest-modal-backdrop" id="guestModalBackdrop" onClick={onClose} />
            <div className="guest-modal" id="guestModal" role="dialog" aria-modal="true" aria-labelledby="guestModalTitle">
                <div className="guest-modal-content">
                    <div className="guest-modal-header">
                        <button className="guest-modal-close" id="guestModalClose" onClick={onClose} aria-label="Закрыть">
                            ×
                        </button>
                    </div>
                    <div className="guest-modal-body">
                        <h2 id="guestModalTitle" className="guest-modal-title">
                            Попробуйте расширенные<br />функции бесплатно
                        </h2>
                        <p className="guest-modal-description">
                            Получайте более разумные ответы, загружайте файлы,
                            создавайте изображения и многое другое.
                        </p>
                        <div className="guest-modal-actions">
                            <button className="guest-modal-btn guest-modal-register" id="guestModalRegisterBtn" onClick={() => { onClose(); onShowRegister(); }}>
                                Зарегистрироваться бесплатно
                            </button>
                            <button className="guest-modal-btn guest-modal-login" id="guestModalLoginBtn" onClick={() => { onClose(); onOpenAuth(); }}>
                                Войти
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </>
    );
};


export const GuestEmptyState = ({ onOpenAuth, onShowRegister }) => {
    return (
        <div className="guest-empty-state">
            <h1 className="guest-empty-title">Добро пожаловать в ReMind</h1>
            <p className="guest-empty-description">
                Ваш персональный ассистент для продуктивности, обучения и развития
            </p>
            <div className="guest-empty-features">
                <div className="guest-feature-item">
                    <div className="guest-feature-icon">💡</div>
                    <p className="guest-feature-text">Умные ответы</p>
                </div>
                <div className="guest-feature-item">
                    <div className="guest-feature-icon">📁</div>
                    <p className="guest-feature-text">Загружайте файлы</p>
                </div>
                <div className="guest-feature-item">
                    <div className="guest-feature-icon">🎨</div>
                    <p className="guest-feature-text">Создавайте изображения</p>
                </div>
                <div className="guest-feature-item">
                    <div className="guest-feature-icon">⚡</div>
                    <p className="guest-feature-text">Быстро и просто</p>
                </div>
            </div>
            <div className="guest-cta-buttons">
                <button className="guest-cta-btn guest-cta-register" id="guestEmptyRegisterBtn" onClick={onShowRegister}>
                    Зарегистрироваться бесплатно
                </button>
                <button className="guest-cta-btn guest-cta-login" id="guestEmptyLoginBtn" onClick={onOpenAuth}>
                    Уже есть аккаунт? Войти
                </button>
            </div>
        </div>
    );
};
