import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
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
import { useURLRouter } from './hooks/useURLRouter';
import { notifyThinkingDone } from './utils/notifications';
import { ALLOW_GUEST_CHATS_SAVE } from './utils/constants';
import GlobalHeader from './features/chat/components/GlobalHeader';
import ShareModal from './features/share/components/ShareModal';
import { useSessionList } from './features/sessions/hooks/useSessionList';

type AuthModalState = false | 'login' | 'register';

type WindowWithLayoutModals = Window & {
    openHtmlPreviewModal?: (urlOrHtml: string, isHtml?: boolean) => void;
    closeHtmlPreviewModal?: () => void;
    openImageLightbox?: (imageSrc: string, messageId?: string) => void;
    closeImageLightbox?: () => void;
};

interface HtmlPreviewState {
    isOpen: boolean;
    urlOrHtml: string | null;
    isHtml: boolean;
}

interface ImageLightboxState {
    isOpen: boolean;
    imageSrc: string | null;
    messageId: string | null;
}

const MOBILE_RAIL_MEDIA_QUERY = '(max-width: 1024px)';

const MainLayout = () => {
    const [isRailExpandedDesktop, setRailExpandedDesktop] = useState(true);
    const [isMobileRailOpen, setMobileRailOpen] = useState(false);
    const [isMobileViewport, setIsMobileViewport] = useState(() =>
        typeof window !== 'undefined' ? window.matchMedia(MOBILE_RAIL_MEDIA_QUERY).matches : false
    );
    const [isSettingsOpen, setSettingsOpen] = useState(false);
    const [isAuthOpen, setAuthOpen] = useState<AuthModalState>(false);
    const [htmlPreview, setHtmlPreview] = useState<HtmlPreviewState>({ isOpen: false, urlOrHtml: null, isHtml: false });
    const [imageLightbox, setImageLightbox] = useState<ImageLightboxState>({ isOpen: false, imageSrc: null, messageId: null });
    const [shareModalOpen, setShareModalOpen] = useState(false);
    const [currentModel, setCurrentModel] = useState('gemini');
    const [initialPrompt, setInitialPrompt] = useState<string | null>(null);

    const { isSettingsView, clearHash } = useURLRouter();
    const { isAuthenticated, loading: isAuthLoading } = useAuth();
    const { settings } = useSettings();

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
        disableSharing,
    } = useChat();

    const { sessions, refreshSessions, onSessionRenamed } = useSessionList({
        isAuthenticated,
        allowGuestChatsSave: ALLOW_GUEST_CHATS_SAVE,
    });

    const isRailExpanded = isMobileViewport ? isMobileRailOpen : isRailExpandedDesktop;

    useEffect(() => {
        if (typeof window === 'undefined') {
            return;
        }

        const mediaQuery = window.matchMedia(MOBILE_RAIL_MEDIA_QUERY);
        const handleViewportChange = (event: MediaQueryListEvent) => {
            setIsMobileViewport(event.matches);
        };

        setIsMobileViewport(mediaQuery.matches);
        mediaQuery.addEventListener('change', handleViewportChange);

        return () => mediaQuery.removeEventListener('change', handleViewportChange);
    }, []);

    useEffect(() => {
        if (!isMobileViewport || !isAuthenticated) {
            setMobileRailOpen(false);
        }
    }, [isAuthenticated, isMobileViewport]);

    useLayoutEffect(() => {
        const hasDesktopRail = !!isAuthenticated && !isMobileViewport;
        const isDesktopRailOpen = hasDesktopRail && !!isRailExpandedDesktop;
        const isMobileOverlayOpen = !!isAuthenticated && isMobileViewport && !!isMobileRailOpen;

        document.body.classList.toggle('has-rail', hasDesktopRail);
        document.body.classList.toggle('rail-open', isDesktopRailOpen);
        document.body.classList.toggle('mobile-menu-open', isMobileOverlayOpen);
    }, [isAuthenticated, isMobileViewport, isMobileRailOpen, isRailExpandedDesktop]);

    useEffect(() => {
        return () => {
            document.body.classList.remove('has-rail');
            document.body.classList.remove('rail-open');
            document.body.classList.remove('mobile-menu-open');
        };
    }, []);

    useEffect(() => {
        const appWindow = window as WindowWithLayoutModals;

        appWindow.openHtmlPreviewModal = (urlOrHtml, isHtml = false) => {
            setHtmlPreview({ isOpen: true, urlOrHtml, isHtml });
        };
        appWindow.closeHtmlPreviewModal = () => {
            setHtmlPreview({ isOpen: false, urlOrHtml: null, isHtml: false });
        };
        appWindow.openImageLightbox = (imageSrc, messageId) => {
            setImageLightbox({ isOpen: true, imageSrc, messageId: messageId ?? null });
        };
        appWindow.closeImageLightbox = () => {
            setImageLightbox({ isOpen: false, imageSrc: null, messageId: null });
        };

        return () => {
            delete appWindow.openHtmlPreviewModal;
            delete appWindow.closeHtmlPreviewModal;
            delete appWindow.openImageLightbox;
            delete appWindow.closeImageLightbox;
        };
    }, []);

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
                return;
            }
            clearChat();
        };

        handleRouteChange();
        window.addEventListener('popstate', handleRouteChange);

        return () => window.removeEventListener('popstate', handleRouteChange);
    }, [loadSession, clearChat]);

    const handleSendMessage = useCallback(
        (text: string, files: File[], options = {}) => {
            const path = window.location.pathname;
            if (path === '/' || !path.startsWith('/c/')) {
                clearChat();
            }

            notifyOnDoneRef.current = true;
            sendMessage(text, files, currentModel, options);
        },
        [clearChat, sendMessage, currentModel]
    );

    useEffect(() => {
        const params = new URLSearchParams(window.location.search);
        let shouldUpdateURL = false;

        const prompt = params.get('prompt');
        if (prompt) {
            const decodedPrompt = decodeURIComponent(prompt);
            setTimeout(() => {
                setInitialPrompt(decodedPrompt);
                if (params.get('auto_send') === 'true') {
                    setTimeout(() => {
                        handleSendMessage(decodedPrompt, [], {});
                        setInitialPrompt(null);
                    }, 100);
                }
            }, 0);
            shouldUpdateURL = true;
        }

        const model = params.get('model');
        if (model) {
            setTimeout(() => setCurrentModel(decodeURIComponent(model)), 0);
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
            if (!isSettingsView()) {
                return;
            }
            if (isAuthLoading) {
                return;
            }
            if (!isAuthenticated) {
                setSettingsOpen(false);
                clearHash();
                return;
            }
            if (!isSettingsOpen) {
                setSettingsOpen(true);
            }
        };

        window.addEventListener('hashRouteChange', handleHashRouteChange as EventListener);

        if (isSettingsView() && !isAuthLoading) {
            if (!isAuthenticated) {
                if (isSettingsOpen) {
                    setTimeout(() => setSettingsOpen(false), 0);
                }
                setTimeout(() => clearHash(), 0);
            } else if (!isSettingsOpen) {
                setTimeout(() => setSettingsOpen(true), 0);
            }
        }

        return () => window.removeEventListener('hashRouteChange', handleHashRouteChange as EventListener);
    }, [isSettingsView, isSettingsOpen, isAuthenticated, isAuthLoading, clearHash]);

    useEffect(() => {
        const closeMenu = () => {
            setMobileRailOpen(false);
        };

        const handleOverlayClick = (event: MouseEvent) => {
            if (!isMobileViewport || !isMobileRailOpen) {
                return;
            }

            const body = document.body;
            const appRail = document.getElementById('appRail');
            const globalControls = document.querySelector('.global-controls');
            const target = event.target as Node | null;

            if (
                (target === body ||
                    target === document.querySelector('main') ||
                    (globalControls && target && !globalControls.contains(target))) &&
                (!appRail || !target || !appRail.contains(target))
            ) {
                closeMenu();
            }
        };

        let touchStartX = 0;
        let touchStartY = 0;

        const handleTouchStart = (event: TouchEvent) => {
            touchStartX = event.changedTouches[0].screenX;
            touchStartY = event.changedTouches[0].screenY;
        };

        const handleTouchEnd = (event: TouchEvent) => {
            const touchEndX = event.changedTouches[0].screenX;
            const touchEndY = event.changedTouches[0].screenY;

            if (!isMobileViewport || !isMobileRailOpen) {
                return;
            }

            const swipeDistanceX = touchStartX - touchEndX;
            const swipeDistanceY = Math.abs(touchStartY - touchEndY);
            if (swipeDistanceX > 50 && swipeDistanceY < 100) {
                closeMenu();
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
    }, [isMobileRailOpen, isMobileViewport]);

    const handleRailToggle = useCallback(() => {
        if (isMobileViewport) {
            setMobileRailOpen((prev) => !prev);
            return;
        }

        setRailExpandedDesktop((prev) => !prev);
    }, [isMobileViewport]);

    const handleSelectSession = useCallback(
        (id: string) => {
            loadSession(id);
            setMobileRailOpen(false);
        },
        [loadSession]
    );

    const handleNewChat = useCallback(() => {
        clearChat();
        window.history.pushState({}, '', '/');
        setMobileRailOpen(false);
    }, [clearChat]);

    return (
        <>
            <SEOHelmet />

            {isAuthenticated && (
                <AppRail
                    isExpanded={isRailExpanded}
                    onToggle={handleRailToggle}
                    sessions={sessions}
                    onSelectSession={handleSelectSession}
                    onNewChat={handleNewChat}
                    onSettingsClick={() => setSettingsOpen(true)}
                    onSessionDeleted={() => {
                        refreshSessions();
                    }}
                    onSessionRenamed={onSessionRenamed}
                />
            )}

            <main className="ui-app-main-shell">
                <GlobalHeader
                    isAuthenticated={isAuthenticated}
                    onMenuToggle={handleRailToggle}
                    currentModel={currentModel}
                    onModelChange={setCurrentModel}
                    onOpenAuth={() => setAuthOpen('login')}
                    onShowRegister={() => setAuthOpen('register')}
                    shareInfo={sessionAccess}
                    currentSessionId={currentSessionId}
                    isReadOnly={isReadOnly}
                    onOpenShareModal={() => setShareModalOpen(true)}
                    onNewChat={handleNewChat}
                />

                {history.length === 0 ? (
                    <div className="ui-empty-conversation-shell">
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
                    onOpenAuth={() => {
                        setSettingsOpen(false);
                        setAuthOpen('login');
                        clearHash();
                    }}
                />
            )}

            {(isAuthOpen === 'login' || isAuthOpen === 'register') && (
                <AuthModal
                    onClose={() => setAuthOpen(false)}
                    initialView={isAuthOpen === 'register' ? 'register' : 'login'}
                />
            )}

            <HtmlPreviewModal
                isOpen={htmlPreview.isOpen}
                onClose={() => setHtmlPreview({ isOpen: false, urlOrHtml: null, isHtml: false })}
                urlOrHtml={htmlPreview.urlOrHtml}
                isHtml={htmlPreview.isHtml}
            />

            <ImageLightbox
                isOpen={imageLightbox.isOpen}
                imageSrc={imageLightbox.imageSrc}
                messageElement={
                    imageLightbox.messageId
                        ? document.querySelector(`[data-message-id="${imageLightbox.messageId}"]`)
                        : null
                }
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
