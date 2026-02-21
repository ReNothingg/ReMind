import React, { useState, useEffect, useLayoutEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { AuthProvider } from './context/AuthContext';
import { SettingsProvider, useSettings } from './context/SettingsContext';
import AppRail from './components/Layout/AppRail';
import ChatContainer from './components/Chat/ChatContainer';
import LandingHero from './components/Chat/LandingHero';
import InputArea from './components/Chat/InputArea';
import SettingsModal from './components/Modals/SettingsModal';
import AuthModal from './components/Modals/AuthModal';
import HtmlPreviewModal from './components/Modals/HtmlPreviewModal';
import ImageLightbox from './components/Modals/ImageLightbox';
import SEOHelmet from './components/UI/SEOHelmet';
import { useChat } from './hooks/useChat';
import { apiService } from './services/api';
import { useURLRouter } from './hooks/useURLRouter';
import { GuestButtons, GuestModal, GuestEmptyState } from './components/GuestMode/GuestModeManager';
import { useAuth } from './context/AuthContext';
import { ALLOW_GUEST_CHATS_SAVE } from './utils/constants';
import { notifyThinkingDone } from './utils/notifications';


const ShareModal = ({
    isOpen,
    onClose,
    shareInfo,
    onEnableShare,
    onDisableShare,
    isAuthenticated,
}) => {
    const { t } = useTranslation();

    if (!isOpen) return null;
    const isShared = !!shareInfo?.isPublic;
    const shareUrl = shareInfo?.shareUrl || (shareInfo?.publicId ? `${window.location.origin}/c/${shareInfo.publicId}` : '');

    return (
        <div className="share-modal-overlay" onClick={onClose}>
            <div className="share-modal" onClick={(e) => e.stopPropagation()}>
                <div className="share-modal-header">
                    <div className="share-modal-title">{t('share.title')}</div>
                    <button className="share-modal-close" onClick={onClose} aria-label={t('share.close')}>
                        ✕
                    </button>
                </div>

                <div className="share-modal-body">
                    {!isAuthenticated && (
                        <div className="share-alert">
                            {t('share.signinToManage')}
                        </div>
                    )}

                    <div className="share-row">
                        <div className="share-label">{t('share.status')}</div>
                        <div className="share-status">
                            <span className={`share-badge ${isShared ? 'shared' : 'private'}`}>
                                {isShared ? t('share.public') : t('share.private')}
                            </span>
                        </div>
                        <button
                            className="share-toggle-btn"
                            onClick={isShared ? onDisableShare : onEnableShare}
                            disabled={!isAuthenticated}
                        >
                            {isShared ? t('share.disable') : t('share.enable')}
                        </button>
                    </div>

                    <div className="share-row">
                        <div className="share-label">{t('share.publicLink')}</div>
                        <div className="share-link">
                            <input
                                type="text"
                                value={isShared ? shareUrl : t('share.enableFirst')}
                                readOnly
                            />
                            <button
                                className="share-copy-icon"
                                onClick={async () => {
                                    if (!isShared || !shareUrl) return;
                                    try {
                                        await navigator.clipboard.writeText(shareUrl);
                                    } catch (e) {
                                        console.warn('Copy failed', e);
                                    }
                                }}
                                disabled={!isShared || !shareUrl}
                                title={t('share.copyLink')}
                                aria-label={t('share.copyLink')}
                            >
                                <img src=" /icons/ui/copy.svg" alt="copy" />
                            </button>
                        </div>
                    </div>

                    <div className="share-tip">
                        {t('share.tip')}
                    </div>
                </div>
            </div>
        </div>
    );
};


const GlobalHeader = ({
    onMenuToggle,
    currentModel,
    onModelChange,
    onGuestModalOpen,
    onOpenAuth,
    onShowRegister,
    shareInfo,
    onEnableShare,
    onDisableShare,
    currentSessionId,
    isReadOnly,
    onOpenShareModal,
    onNewChat
}) => {
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
    const dropdownRef = useRef(null);
    const { isAuthenticated } = useAuth();
    const { t } = useTranslation();

    useEffect(() => {
        const handleClickOutside = (event) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
                setIsDropdownOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const models = [
        { id: 'gemini', name: 'Gemini', desc: t('models.gemini.desc'), badge: t('models.gemini.badge') },

        { id: 'echo', name: 'Echo', desc: t('models.echo.desc') },
    ];

    const activeModel = models.find(m => m.id === currentModel) || models[0];

    const isShared = !!shareInfo?.isPublic;
    const canShare = isAuthenticated && !!currentSessionId && shareInfo?.isOwner !== false;

    return (
        <div className="global-controls">
            {!isAuthenticated && (
                <GuestButtons
                    onOpenAuth={onOpenAuth}
                    onShowRegister={onShowRegister}
                />
            )}
            {isAuthenticated && (
                <button id="mobileMenuToggle" className="mobile-menu-btn" onClick={onMenuToggle} title={t('app.menu')}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="3" y1="12" x2="21" y2="12"></line>
                        <line x1="3" y1="6" x2="21" y2="6"></line>
                        <line x1="3" y1="18" x2="21" y2="18"></line>
                    </svg>
                </button>
            )}

            {isAuthenticated ? (
                <div className="model-selector-new" ref={dropdownRef}>
                <button
                    className={`model-btn-trigger ${isDropdownOpen ? 'open' : ''}`}
                    onClick={(e) => {
                        if (!isAuthenticated) {
                            e.preventDefault();
                            e.stopPropagation();
                            onGuestModalOpen();
                            return false;
                        }
                        setIsDropdownOpen(!isDropdownOpen);
                    }}
                >
                    <span className="model-btn-icon"></span>
                    <span className="model-btn-name">{activeModel.name}</span>
                    <svg className="model-btn-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polyline points="6 9 12 15 18 9"></polyline>
                    </svg>
                </button>

                <div className={`model-dropdown ${isDropdownOpen ? 'open' : ''}`}>
                    <div className="model-dropdown-header">
                        <span className="model-dropdown-title">{t('models.choose')}</span>
                        <button className="model-dropdown-close" onClick={() => setIsDropdownOpen(false)}>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <line x1="18" y1="6" x2="6" y2="18"></line>
                                <line x1="6" y1="6" x2="18" y2="18"></line>
                            </svg>
                        </button>
                    </div>
                    <div className="model-options">
                        {models.map(model => (
                            <div
                                key={model.id}
                                className="model-option"
                                aria-selected={currentModel === model.id}
                                onClick={(e) => {
                                    if (!isAuthenticated) {
                                        e.preventDefault();
                                        e.stopPropagation();
                                        setIsDropdownOpen(false);
                                        if (onShowRegister) onShowRegister();
                                        return false;
                                    }
                                    onModelChange(model.id);
                                    setIsDropdownOpen(false);
                                }}
                            >
                                <div className="model-option-header">
                                    <span className="model-option-name">{model.name}</span>
                                    {model.badge && <span className="model-option-badge">{model.badge}</span>}
                                </div>
                                <span className="model-option-desc">{model.desc}</span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
            ) : (
                <div className="model-selector-new" ref={dropdownRef}>
                    <button
                        className="model-btn-trigger"
                    onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        if (onOpenAuth) {
                            onOpenAuth();
                        } else if (onGuestModalOpen) {
                            onGuestModalOpen();
                        }
                    }}
                    >
                        <span className="model-btn-icon"></span>
                        <span className="model-btn-name">Gemini</span>
                        <svg className="model-btn-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                    </button>
                </div>
            )}

            {!!currentSessionId && (
                <div className="share-controls">
                    <button
                        className={`icon-btn share-icon ${isShared ? 'active' : ''}`}
                        onClick={() => {
                            if (!canShare && onOpenAuth) return onOpenAuth();
                            onOpenShareModal?.();
                        }}
                        title={isShared ? t('share.configure') : t('share.shareChat')}
                        aria-label={t('share.shareChat')}
                        disabled={!canShare}
                    >
                        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2">
                            <circle cx="6" cy="12" r="3"></circle>
                            <circle cx="18" cy="6" r="3"></circle>
                            <circle cx="18" cy="18" r="3"></circle>
                            <line x1="8.7" y1="10.7" x2="15.3" y2="7.3"></line>
                            <line x1="8.7" y1="13.3" x2="15.3" y2="16.7"></line>
                        </svg>
                    </button>
                    {(isReadOnly || isShared) && (
                        <span className="readonly-pill" title={isReadOnly ? t('share.readOnly') : t('share.publicChat')}>
                            {isReadOnly ? t('chat.readOnly') : t('share.publicChat')}
                        </span>
                    )}
                </div>
            )}

            {isAuthenticated && (
                <button
                    className="new-chat-btn"
                    onClick={onNewChat}
                    title={t('rail.newChat')}
                    aria-label={t('rail.newChat')}
                >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 5v14M5 12h14"></path>
                    </svg>
                </button>
            )}
        </div>
    );
};


	const MainLayout = () => {
	    const [sessions, setSessions] = useState([]);
	    const [isRailExpanded, setRailExpanded] = useState(true);
    const [isSettingsOpen, setSettingsOpen] = useState(false);
    const [isAuthOpen, setAuthOpen] = useState(false);
    const [htmlPreview, setHtmlPreview] = useState({ isOpen: false, urlOrHtml: null, isHtml: false });
    const [guestModalOpen, setGuestModalOpen] = useState(false);
    const [imageLightbox, setImageLightbox] = useState({ isOpen: false, imageSrc: null, messageId: null });
    const [shareModalOpen, setShareModalOpen] = useState(false);
    const { isSettingsView, clearHash } = useURLRouter();
    const { isAuthenticated } = useAuth();
    const { settings } = useSettings();


    const [currentModel, setCurrentModel] = useState('gemini');
	    useLayoutEffect(() => {
	        document.body.classList.toggle('has-rail', !!isAuthenticated);
	        document.body.classList.toggle('rail-open', !!isAuthenticated && !!isRailExpanded);
	    }, [isAuthenticated, isRailExpanded]);

	    useEffect(() => {
	        return () => {
	            document.body.classList.remove('has-rail');
	            document.body.classList.remove('rail-open');
	        };
	    }, []);

    useEffect(() => {
        window.openHtmlPreviewModal = (urlOrHtml, isHtml = false) => {
            setHtmlPreview({ isOpen: true, urlOrHtml, isHtml });
        };
        window.closeHtmlPreviewModal = () => {
            setHtmlPreview({ isOpen: false, urlOrHtml: null, isHtml: false });
        };
        window.openImageLightbox = (imageSrc, messageId) => {
            setImageLightbox({ isOpen: true, imageSrc, messageId });
        };
        window.closeImageLightbox = () => {
            setImageLightbox({ isOpen: false, imageSrc: null, messageId: null });
        };
        return () => {
            delete window.openHtmlPreviewModal;
            delete window.closeHtmlPreviewModal;
            delete window.openImageLightbox;
            delete window.closeImageLightbox;
        };
    }, []);


    const {
        history,
        isLoading,
        sendMessage,
        stopGeneration,
        loadSession,
        clearChat,
        currentSessionId,
        regenerateMessage,
        editMessage,
        switchVariant,
        sessionAccess,
        isReadOnly,
        enableSharing,
        disableSharing
    } = useChat();

    const wasLoadingRef = useRef(false);
    const notifyOnDoneRef = useRef(false);
    useEffect(() => {
        const wasLoading = wasLoadingRef.current;
        wasLoadingRef.current = isLoading;
        if (wasLoading && !isLoading && settings.notifyOnThinkingDone && notifyOnDoneRef.current) {
            notifyThinkingDone();
            notifyOnDoneRef.current = false;
        }
    }, [isLoading, settings.notifyOnThinkingDone]);


    const refreshSessions = useCallback(async () => {
        try {
            if (isAuthenticated) {

                const data = await apiService.listSessions();
                if (data?.sessions) setSessions(data.sessions);
            } else {

                if (ALLOW_GUEST_CHATS_SAVE) {
                    try {
                        const guestIds = JSON.parse(localStorage.getItem('guest_chat_history_ids') || '[]');
                        if (guestIds.length > 0) {
                            const query = guestIds.join(',');
                            const data = await apiService.listSessions(query);
                            if (data?.sessions) setSessions(data.sessions);
                        } else {
                            setSessions([]);
                        }
                    } catch (e) {
                        console.warn("Ошибка загрузки гостевых сессий:", e);
                        setSessions([]);
                    }
                } else {
                    setSessions([]);
                }
            }
        } catch (e) {
            console.error("Ошибка загрузки списка чатов:", e);
            setSessions([]);
        }
    }, [isAuthenticated]);

    const onSessionRenamed = useCallback((sessionId, newTitle) => {
        setSessions(prevSessions =>
            prevSessions.map(s =>
                s.session_id === sessionId
                    ? { ...s, title: newTitle }
                    : s
            )
        );
    }, []);

    useEffect(() => {

        const handleRouteChange = () => {
            const path = window.location.pathname;
            if (path.startsWith('/c/')) {
                const slug = decodeURIComponent(path.split('/c/')[1]);
                if (slug) {
                    loadSession(slug);
                } else {
                    clearChat();
                }
            } else {
                clearChat();
            }
        };


        handleRouteChange();


        window.addEventListener('popstate', handleRouteChange);
        return () => window.removeEventListener('popstate', handleRouteChange);
    }, [loadSession, clearChat]);


    const [initialPrompt, setInitialPrompt] = useState(null);


    const handleSendMessage = useCallback((text, files, options = {}) => {

        const path = window.location.pathname;
        if (path === '/' || !path.startsWith('/c/')) {
            clearChat();

        }
        notifyOnDoneRef.current = true;
        sendMessage(text, files, currentModel, options);
    }, [clearChat, sendMessage, currentModel]);


    useEffect(() => {
        const params = new URLSearchParams(window.location.search);
        let shouldUpdateURL = false;


        if (params.get('prompt')) {
            const prompt = decodeURIComponent(params.get('prompt'));

            setTimeout(() => {
                setInitialPrompt(prompt);
                if (params.get('auto_send') === 'true') {

                    setTimeout(() => {
                        handleSendMessage(prompt, [], {});
                        setInitialPrompt(null);
                    }, 100);
                }
            }, 0);
            shouldUpdateURL = true;
        }


        if (params.get('model')) {
            const model = decodeURIComponent(params.get('model'));
            setTimeout(() => setCurrentModel(model), 0);
            shouldUpdateURL = true;
        }





        if (shouldUpdateURL && params.toString()) {
            const cleanURL = `${window.location.pathname}${window.location.hash}`;
            window.history.replaceState(null, '', cleanURL);
        }
    }, [handleSendMessage]);


    useEffect(() => {
        setTimeout(() => refreshSessions(), 0);
    }, [refreshSessions]);


    useEffect(() => {
        if (currentSessionId) {

            setTimeout(() => refreshSessions(), 0);
        }
    }, [currentSessionId, refreshSessions]);


    useEffect(() => {
        const handleHashRouteChange = () => {
            if (isSettingsView()) {
                if (!isSettingsOpen) {
                    setSettingsOpen(true);
                }

            }
        };

        window.addEventListener('hashRouteChange', handleHashRouteChange);

        if (isSettingsView() && !isSettingsOpen) {

            setTimeout(() => setSettingsOpen(true), 0);
        }
        return () => window.removeEventListener('hashRouteChange', handleHashRouteChange);
    }, [isSettingsView, isSettingsOpen]);
    useEffect(() => {
        const closeMenu = () => {
            document.body.classList.remove('mobile-menu-open');
        };
        const handleOverlayClick = (e) => {
            const body = document.body;
            const isMenuOpen = body.classList.contains('mobile-menu-open');
            if (isMenuOpen) {
                const appRail = document.getElementById('appRail');
                const globalControls = document.querySelector('.global-controls');

                if (
                    (e.target === body ||
                     e.target === document.querySelector('main') ||
                     (globalControls && !globalControls.contains(e.target))) &&
                    (!appRail || !appRail.contains(e.target))
                ) {
                    closeMenu();
                }
            }
        };
        let touchStartX = 0;
        let touchStartY = 0;
        let touchEndX = 0;
        let touchEndY = 0;

        const handleTouchStart = (e) => {
            touchStartX = e.changedTouches[0].screenX;
            touchStartY = e.changedTouches[0].screenY;
        };

        const handleTouchEnd = (e) => {
            touchEndX = e.changedTouches[0].screenX;
            touchEndY = e.changedTouches[0].screenY;
            const body = document.body;
            const isMenuOpen = body.classList.contains('mobile-menu-open');

            if (isMenuOpen) {
                const swipeDistanceX = touchStartX - touchEndX;
                const swipeDistanceY = Math.abs(touchStartY - touchEndY);
                if (swipeDistanceX > 50 && swipeDistanceY < 100) {
                    closeMenu();
                }
            }
        };

        document.addEventListener('click', handleOverlayClick);
        document.addEventListener('touchstart', handleTouchStart);
        document.addEventListener('touchend', handleTouchEnd);

        return () => {
            document.removeEventListener('click', handleOverlayClick);
            document.removeEventListener('touchstart', handleTouchStart);
            document.removeEventListener('touchend', handleTouchEnd);
        };
    }, []);


    return (
        <>
            <SEOHelmet />
	            {isAuthenticated && (
	                <AppRail
	                    isExpanded={isRailExpanded}
	                    onToggle={() => {
	                        setRailExpanded(!isRailExpanded);
	                    }}
	                    sessions={sessions}
	                    onSelectSession={(id) => {
	                        loadSession(id);

                        document.body.classList.remove('mobile-menu-open');
                    }}
                    onNewChat={() => {
                        clearChat();
                        window.history.pushState({}, '', '/');
                    }}
                    onSettingsClick={() => setSettingsOpen(true)}
                    onSessionDeleted={() => {
                        refreshSessions();
                    }}
                    onSessionRenamed={onSessionRenamed}
                />
            )}

            <main>
                <GlobalHeader
                    onMenuToggle={() => document.body.classList.toggle('mobile-menu-open')}
                    currentModel={currentModel}
                    onModelChange={setCurrentModel}
                    onGuestModalOpen={() => setGuestModalOpen(true)}
                    onOpenAuth={() => setAuthOpen('login')}
                    onShowRegister={() => setAuthOpen('register')}
                    shareInfo={sessionAccess}
                    onEnableShare={enableSharing}
                    onDisableShare={disableSharing}
                    currentSessionId={currentSessionId}
                    isReadOnly={isReadOnly}
                    onOpenShareModal={() => setShareModalOpen(true)}
                    onNewChat={() => {
                        clearChat();
                        window.history.pushState({}, '', '/');
                        document.body.classList.remove('mobile-menu-open');
                    }}
                />

                {history.length === 0 ? (
                    <div className="landing-shell">
                        <LandingHero isReadOnly={isReadOnly}>
                            <InputArea
                                variant="landing"
                                showDynamicWarning={false}
                                onSendMessage={handleSendMessage}
                                onStop={() => {
                                    notifyOnDoneRef.current = false;
                                    stopGeneration();
                                }}
                                isLoading={isLoading}
                                isReadOnly={isReadOnly}
                                initialPrompt={initialPrompt}
                                onOpenAuth={() => setAuthOpen('login')}
                            />
                        </LandingHero>
                    </div>
                ) : (
                    <>
                        <ChatContainer
                            history={history}
                            isLoading={isLoading}
                            isReadOnly={isReadOnly}
                            onRegenerate={(messageId) => {
                                if (regenerateMessage) {
                                    notifyOnDoneRef.current = true;
                                    regenerateMessage(messageId, currentModel);
                                }
                            }}
                            onEdit={(messageId, newText) => {
                                if (editMessage) {
                                    notifyOnDoneRef.current = true;
                                    editMessage(messageId, newText, currentModel);
                                }
                            }}
                            onSwitchVariant={(messageId, direction) => {
                                if (switchVariant) {
                                    switchVariant(messageId, direction);
                                }
                            }}
                        />

                        <InputArea
                            onSendMessage={handleSendMessage}
                            onStop={() => {
                                notifyOnDoneRef.current = false;
                                stopGeneration();
                            }}
                            isLoading={isLoading}
                            isReadOnly={isReadOnly}
                            initialPrompt={initialPrompt}
                            onOpenAuth={() => setAuthOpen('login')}
                        />
                    </>
                )}
            </main>

            {isSettingsOpen && (
                <SettingsModal
                    onClose={() => {
                        setSettingsOpen(false);
                        clearHash();
                    }}
                    onOpenAuth={() => { setSettingsOpen(false); setAuthOpen('login'); clearHash(); }}
                />
            )}

            {(isAuthOpen === 'login' || isAuthOpen === 'register') && (
                <AuthModal
                    onClose={() => setAuthOpen(false)}
                    initialView={isAuthOpen === 'register' ? 'register' : 'login'}
                />
            )}

            <GuestModal
                isOpen={guestModalOpen}
                onClose={() => setGuestModalOpen(false)}
                onOpenAuth={() => {
                    setGuestModalOpen(false);
                    setAuthOpen('login');
                }}
                onShowRegister={() => {
                    setGuestModalOpen(false);
                    setAuthOpen('register');
                }}
            />

            <HtmlPreviewModal
                isOpen={htmlPreview.isOpen}
                onClose={() => setHtmlPreview({ isOpen: false, urlOrHtml: null, isHtml: false })}
                urlOrHtml={htmlPreview.urlOrHtml}
                isHtml={htmlPreview.isHtml}
            />

            <ImageLightbox
                isOpen={imageLightbox.isOpen}
                imageSrc={imageLightbox.imageSrc}
                messageElement={imageLightbox.messageId ? document.querySelector(`[data-message-id="${imageLightbox.messageId}"]`) : null}
                onClose={() => setImageLightbox({ isOpen: false, imageSrc: null, messageId: null })}
                currentModel={currentModel}
                sessionId={currentSessionId}
            />

            <ShareModal
                isOpen={shareModalOpen}
                onClose={() => setShareModalOpen(false)}
                shareInfo={sessionAccess}
                onEnableShare={enableSharing}
                onDisableShare={disableSharing}
                isAuthenticated={isAuthenticated}
            />
        </>
    );
};

const App = () => {
    return (
        <AuthProvider>
            <SettingsProvider>
                <MainLayout />
            </SettingsProvider>
        </AuthProvider>
    );
};

export default App;
