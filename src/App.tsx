import { Suspense, lazy, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { BadgeCheck, BrainCircuit, X } from 'lucide-react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { useTranslation } from 'react-i18next';
import { SettingsProvider, useSettings } from './context/SettingsContext';
import LandingHero from './components/Chat/LandingHero';
import InputArea from './components/Chat/InputArea';
import SEOHelmet from './components/UI/SEOHelmet';
import { apiService, type Mind } from './services/api';
import { useChat } from './hooks/useChat';
import { useURLRouter } from './hooks/useURLRouter';
import { notifyThinkingDone } from './utils/notifications';
import { ALLOW_GUEST_CHATS_SAVE } from './utils/constants';
import GlobalHeader from './features/chat/components/GlobalHeader';
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
const AppRail = lazy(() => import('./components/Layout/AppRail'));
const ChatContainer = lazy(() => import('./components/Chat/ChatContainer'));
const SettingsModal = lazy(() => import('./components/Modals/SettingsModal'));
const AuthModal = lazy(() => import('./components/Modals/AuthModal'));
const HtmlPreviewModal = lazy(() => import('./components/Modals/HtmlPreviewModal'));
const ImageLightbox = lazy(() => import('./components/Modals/ImageLightbox'));
const ShareModal = lazy(() => import('./features/share/components/ShareModal'));
const MindsPage = lazy(() => import('./features/minds/MindsPage'));
const MindEditorPage = lazy(() => import('./features/minds/MindEditorPage'));

function normalizeAppPath(path: string): string {
    if (path === '/editor') {
        return '/minds/editor';
    }
    if (path.startsWith('/editor/')) {
        return `/minds/editor/${path.slice('/editor/'.length)}`;
    }
    return path;
}

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
    const [routePath, setRoutePath] = useState(() =>
        typeof window !== 'undefined' ? window.location.pathname : '/'
    );
    const [activeMind, setActiveMind] = useState<Mind | null>(null);
    const [pinnedMinds, setPinnedMinds] = useState<Mind[]>([]);

    const { isSettingsView, clearHash } = useURLRouter();
    const { isAuthenticated, loading: isAuthLoading } = useAuth();
    const { settings } = useSettings();
    const { t } = useTranslation();

    const {
        history,
        isLoading,
        sendMessage,
        stopGeneration,
        loadSession,
        clearChat,
        setActiveSessionMindId,
        currentSessionId,
        regenerateMessage,
        editMessage,
        switchVariant,
        sessionAccess,
        isReadOnly,
        enableSharing,
        disableSharing,
    } = useChat();

    const { sessions, refreshSessions, removeSession, onSessionRenamed } = useSessionList({
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

        mediaQuery.addEventListener('change', handleViewportChange);

        return () => mediaQuery.removeEventListener('change', handleViewportChange);
    }, []);

    useEffect(() => {
        if (isMobileRailOpen && (!isMobileViewport || !isAuthenticated)) {
            const frame = window.requestAnimationFrame(() => setMobileRailOpen(false));
            return () => window.cancelAnimationFrame(frame);
        }
        return undefined;
    }, [isAuthenticated, isMobileRailOpen, isMobileViewport]);

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

        if (wasLoading && !isLoading) {
            if (settings.notifyOnThinkingDone && notifyOnDoneRef.current) {
                notifyThinkingDone();
                notifyOnDoneRef.current = false;
            }
            if (currentSessionId) {
                setTimeout(() => refreshSessions(), 0);
            }
        }
    }, [currentSessionId, isLoading, refreshSessions, settings.notifyOnThinkingDone]);

    const refreshPinnedMinds = useCallback(async () => {
        if (!isAuthenticated) {
            setPinnedMinds([]);
            return;
        }
        try {
            const minds = await apiService.listPinnedMinds();
            setPinnedMinds(minds);
        } catch (error) {
            console.warn('Failed to load pinned minds', error);
            setPinnedMinds([]);
        }
    }, [isAuthenticated]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            void refreshPinnedMinds();
        }, 0);
        return () => window.clearTimeout(timer);
    }, [refreshPinnedMinds]);

    const navigateTo = useCallback((targetPath: string) => {
        const url = new URL(targetPath, window.location.origin);
        const nextPathAndSearch = `${url.pathname}${url.search}`;
        if (`${window.location.pathname}${window.location.search}` !== nextPathAndSearch) {
            window.history.pushState({}, '', nextPathAndSearch);
        }
        setRoutePath(url.pathname);
        window.scrollTo({ top: 0, behavior: 'auto' });
    }, []);

    useEffect(() => {
        const handleRouteChange = () => {
            const path = normalizeAppPath(window.location.pathname);
            if (path !== window.location.pathname) {
                window.history.replaceState({}, '', `${path}${window.location.search}${window.location.hash}`);
            }
            setRoutePath(path);
            if (path.startsWith('/c/')) {
                const slug = decodeURIComponent(path.split('/c/')[1]);
                if (slug) {
                    setActiveMind(null);
                    void loadSession(slug, { historyMode: 'replace' }).then((data) => {
                        if (data) {
                            setActiveMind(data.mind || null);
                        }
                    });
                } else {
                    setActiveMind(null);
                    clearChat({ historyMode: 'none' });
                }
                return;
            }
            clearChat({ historyMode: 'none' });
        };

        handleRouteChange();
        window.addEventListener('popstate', handleRouteChange);

        return () => window.removeEventListener('popstate', handleRouteChange);
    }, [loadSession, clearChat]);

    useEffect(() => {
        if (routePath !== '/') {
            return;
        }

        const mindId = new URLSearchParams(window.location.search).get('mind');
        if (!mindId) {
            return;
        }

        let cancelled = false;
        apiService
            .getMind(mindId)
            .then((mind) => {
                if (!cancelled && mind) {
                    setActiveMind(mind);
                }
            })
            .catch((error) => {
                console.warn('Failed to load active mind', error);
                if (!cancelled) {
                    setActiveMind(null);
                }
            });

        return () => {
            cancelled = true;
        };
    }, [routePath]);

    const handleSendMessage = useCallback(
        (text: string, files: File[], options = {}) => {
            const path = window.location.pathname;
            if (path === '/' || !path.startsWith('/c/')) {
                clearChat({ historyMode: 'none' });
            }

            notifyOnDoneRef.current = true;
            sendMessage(text, files, currentModel, {
                ...options,
                mindId: activeMind?.public_id || null,
            });
        },
        [activeMind, clearChat, sendMessage, currentModel]
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
            if (id === currentSessionId && window.location.pathname.startsWith('/c/')) {
                setMobileRailOpen(false);
                return;
            }
            setActiveMind(null);
            void loadSession(id, { historyMode: 'push' }).then((data) => {
                if (data) {
                    setActiveMind(data.mind || null);
                }
            });
            setMobileRailOpen(false);
        },
        [currentSessionId, loadSession]
    );

    const handleNewChat = useCallback(() => {
        setActiveMind(null);
        clearChat({ historyMode: 'push' });
        setRoutePath('/');
        setMobileRailOpen(false);
    }, [clearChat]);

    const handleMindsClick = useCallback(() => {
        clearChat({ historyMode: 'none' });
        navigateTo('/minds');
        setMobileRailOpen(false);
    }, [clearChat, navigateTo]);

    const handleCreateMind = useCallback(() => {
        clearChat({ historyMode: 'none' });
        navigateTo('/minds/editor');
        setMobileRailOpen(false);
    }, [clearChat, navigateTo]);

    const handleEditMind = useCallback((mind: Mind) => {
        clearChat({ historyMode: 'none' });
        navigateTo(`/minds/editor/${encodeURIComponent(mind.public_id)}`);
        setMobileRailOpen(false);
    }, [clearChat, navigateTo]);

    const handleStartMind = useCallback((mind: Mind) => {
        setActiveMind(mind);
        clearChat({ historyMode: 'none' });
        navigateTo(`/?mind=${encodeURIComponent(mind.public_id)}`);
        setMobileRailOpen(false);
    }, [clearChat, navigateTo]);

    const handleMindSaved = useCallback((mind: Mind) => {
        void refreshPinnedMinds();
        navigateTo('/minds');
        setActiveMind((current) => {
            if (current?.public_id === mind.public_id) {
                return mind;
            }
            return current;
        });
    }, [navigateTo, refreshPinnedMinds]);

    const handleClearActiveMind = useCallback(() => {
        setActiveMind(null);
        setActiveSessionMindId(null);
        if (currentSessionId) {
            void apiService.setSessionMind(currentSessionId, null).catch((error) => {
                console.warn('Failed to clear session mind', error);
            });
        }
        if (window.location.pathname === '/' && window.location.search) {
            window.history.replaceState({}, '', '/');
        }
    }, [currentSessionId, setActiveSessionMindId]);

    const editorMindId = routePath.startsWith('/minds/editor/')
        ? decodeURIComponent(routePath.slice('/minds/editor/'.length))
        : null;
    const isMindsRoute = routePath === '/minds';
    const isEditorRoute = routePath === '/minds/editor' || routePath.startsWith('/minds/editor/');
    const isChatSurface = !isMindsRoute && !isEditorRoute;

    return (
        <>
            <SEOHelmet />

            {isAuthenticated && (
                <Suspense fallback={null}>
                    <AppRail
                        isExpanded={isRailExpanded}
                        onToggle={handleRailToggle}
                        sessions={sessions}
                        currentSessionId={currentSessionId}
                        onSelectSession={handleSelectSession}
                        onNewChat={handleNewChat}
                        onMindsClick={handleMindsClick}
                        onSettingsClick={() => setSettingsOpen(true)}
                        currentPath={routePath}
                        activeMindId={activeMind?.public_id || null}
                        pinnedMinds={pinnedMinds}
                        onSelectMind={handleStartMind}
                        onSessionDeleted={(sessionId) => {
                            removeSession(sessionId);
                            if (sessionId === currentSessionId) {
                                clearChat({ historyMode: 'replace' });
                            }
                            refreshSessions();
                        }}
                        onSessionRenamed={onSessionRenamed}
                    />
                </Suspense>
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
                    showChatControls={isChatSurface}
                />

                {isMindsRoute ? (
                    <Suspense fallback={null}>
                        <MindsPage
                            isAuthenticated={isAuthenticated}
                            onCreateMind={handleCreateMind}
                            onEditMind={handleEditMind}
                            onOpenAuth={() => setAuthOpen('login')}
                            onPinnedChange={refreshPinnedMinds}
                            onStartMind={handleStartMind}
                        />
                    </Suspense>
                ) : isEditorRoute ? (
                    <Suspense fallback={null}>
                        <MindEditorPage
                            editingMindId={editorMindId}
                            isAuthenticated={isAuthenticated}
                            onCancel={() => navigateTo('/minds')}
                            onOpenAuth={() => setAuthOpen('login')}
                            onSaved={handleMindSaved}
                        />
                    </Suspense>
                ) : history.length === 0 ? (
                    <div className="ui-empty-conversation-shell">
                        <LandingHero isReadOnly={isReadOnly}>
                            {activeMind && (
                                <div className="ui-landing-mind-panel">
                                    <div className="ui-landing-mind-header">
                                        <div className="ui-landing-mind-title">
                                            <BrainCircuit size={22} />
                                            <div>
                                                <strong>
                                                    {activeMind.name}
                                                    {activeMind.is_verified && (
                                                        <BadgeCheck size={15} className="ml-1 inline-block align-[-2px]" />
                                                    )}
                                                </strong>
                                                <span>{activeMind.description}</span>
                                            </div>
                                        </div>
                                        <button
                                            type="button"
                                            className="ui-landing-mind-close"
                                            onClick={handleClearActiveMind}
                                            aria-label={t('minds.disableActive')}
                                            title={t('minds.disableActive')}
                                        >
                                            <X size={17} />
                                        </button>
                                    </div>
                                    {activeMind.starters?.length > 0 && (
                                        <div className="ui-landing-mind-starters">
                                            {activeMind.starters.map((starter) => (
                                                <button
                                                    key={starter}
                                                    type="button"
                                                    onClick={() => handleSendMessage(starter, [], {})}
                                                >
                                                    {starter}
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
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
                    <Suspense fallback={null}>
                        <>
                            {activeMind && (
                                <div className="ui-chat-mind-banner" role="status">
                                    <div className="ui-chat-mind-banner-main">
                                        <div className="ui-chat-mind-banner-icon" aria-hidden="true">
                                            <BrainCircuit size={19} />
                                        </div>
                                        <div className="ui-chat-mind-banner-copy">
                                            <span>{t('minds.activeLabel')}</span>
                                            <strong>
                                                {activeMind.name}
                                                {activeMind.is_verified && (
                                                    <BadgeCheck size={14} className="ml-1 inline-block align-[-2px]" />
                                                )}
                                            </strong>
                                            {activeMind.description && (
                                                <p>{activeMind.description}</p>
                                            )}
                                        </div>
                                    </div>
                                    <button
                                        type="button"
                                        className="ui-chat-mind-banner-close"
                                        onClick={handleClearActiveMind}
                                        aria-label={t('minds.disableActive')}
                                        title={t('minds.disableActive')}
                                    >
                                        <X size={16} />
                                    </button>
                                </div>
                            )}
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
                    </Suspense>
                )}
            </main>

            {isSettingsOpen && (
                <Suspense fallback={null}>
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
                </Suspense>
            )}

            {(isAuthOpen === 'login' || isAuthOpen === 'register') && (
                <Suspense fallback={null}>
                    <AuthModal
                        onClose={() => setAuthOpen(false)}
                        initialView={isAuthOpen === 'register' ? 'register' : 'login'}
                    />
                </Suspense>
            )}

            {htmlPreview.isOpen && (
                <Suspense fallback={null}>
                    <HtmlPreviewModal
                        isOpen={htmlPreview.isOpen}
                        onClose={() => setHtmlPreview({ isOpen: false, urlOrHtml: null, isHtml: false })}
                        urlOrHtml={htmlPreview.urlOrHtml}
                        isHtml={htmlPreview.isHtml}
                    />
                </Suspense>
            )}

            {imageLightbox.isOpen && (
                <Suspense fallback={null}>
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
                </Suspense>
            )}

            {shareModalOpen && (
                <Suspense fallback={null}>
                    <ShareModal
                        isOpen={shareModalOpen}
                        onClose={() => setShareModalOpen(false)}
                        shareInfo={sessionAccess}
                        onEnableShare={enableSharing}
                        onDisableShare={disableSharing}
                        isAuthenticated={isAuthenticated}
                    />
                </Suspense>
            )}
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
