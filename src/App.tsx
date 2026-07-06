import { Suspense, lazy, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from 'react';
import { BadgeCheck, BrainCircuit, FileCode2, FileText, PanelRightOpen, LockKeyhole, X } from 'lucide-react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { useTranslation } from 'react-i18next';
import { SettingsProvider, useSettings } from './context/SettingsContext';
import LandingHero from './components/Chat/LandingHero';
import InputArea from './components/Chat/InputArea';
import SEOHelmet from './components/UI/SEOHelmet';
import { apiService, type CanvasTextdoc, type Mind } from './services/api';
import { useChat } from './hooks/useChat';
import { useURLRouter } from './hooks/useURLRouter';
import { notifyThinkingDone } from './utils/notifications';
import { ALLOW_GUEST_CHATS_SAVE } from './utils/constants';
import GlobalHeader from './features/chat/components/GlobalHeader';
import {
    FALLBACK_MODELS,
    getFallbackModelId,
    isModelAvailable,
    normalizeModelOptions,
    type ChatModel,
} from './features/chat/modelSelection';
import { useSessionList, type SessionSummary } from './features/sessions/hooks/useSessionList';

type AuthModalState = false | 'login' | 'register';

type ChatSessionActivity = {
    status?: 'generating' | 'complete' | 'error';
    updatedAt?: number;
};

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
const CANVAS_WIDTH_STORAGE_KEY = 'remind.canvas.width';
const CANVAS_MIN_WIDTH = 360;
const CANVAS_DEFAULT_WIDTH = 520;
const CANVAS_MAX_WIDTH = 820;
const AppRail = lazy(() => import('./components/Layout/AppRail'));
const ChatContainer = lazy(() => import('./components/Chat/ChatContainer'));
const SettingsModal = lazy(() => import('./components/Modals/SettingsModal'));
const AuthModal = lazy(() => import('./components/Modals/AuthModal'));
const HtmlPreviewModal = lazy(() => import('./components/Modals/HtmlPreviewModal'));
const ImageLightbox = lazy(() => import('./components/Modals/ImageLightbox'));
const ShareModal = lazy(() => import('./features/share/components/ShareModal'));
const MindsPage = lazy(() => import('./features/minds/MindsPage'));
const MindEditorPage = lazy(() => import('./features/minds/MindEditorPage'));
const AdminPanel = lazy(() => import('./features/admin/AdminPanel'));
const CanvasPanel = lazy(() => import('./features/canvas/CanvasPanel'));

function clampCanvasWidth(width: number): number {
    if (typeof window === 'undefined') {
        return Math.min(CANVAS_MAX_WIDTH, Math.max(CANVAS_MIN_WIDTH, width));
    }

    const railOffset = Number.parseFloat(
        window.getComputedStyle(document.body).getPropertyValue('--app-rail-offset')
    ) || 0;
    const maxByViewport = Math.max(CANVAS_MIN_WIDTH, window.innerWidth - railOffset - 420);
    return Math.round(Math.min(CANVAS_MAX_WIDTH, maxByViewport, Math.max(CANVAS_MIN_WIDTH, width)));
}

function normalizeAppPath(path: string): string {
    if (path === '/editor') {
        return '/minds/editor';
    }
    if (path.startsWith('/editor/')) {
        return `/minds/editor/${path.slice('/editor/'.length)}`;
    }
    if (path === '/github' || path.startsWith('/github/')) {
        return '/';
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
    const [isCanvasVisible, setCanvasVisible] = useState(false);
    const [selectedCanvasTextdoc, setSelectedCanvasTextdoc] = useState<CanvasTextdoc | null>(null);
    const [canvasWidth, setCanvasWidth] = useState(() => {
        if (typeof window === 'undefined') {
            return CANVAS_DEFAULT_WIDTH;
        }
        const stored = window.localStorage.getItem(CANVAS_WIDTH_STORAGE_KEY);
        const parsed = stored ? Number.parseInt(stored, 10) : CANVAS_DEFAULT_WIDTH;
        return clampCanvasWidth(Number.isFinite(parsed) ? parsed : CANVAS_DEFAULT_WIDTH);
    });
    const [isCanvasResizing, setCanvasResizing] = useState(false);
    const [currentModel, setCurrentModel] = useState('');
    const [availableModels, setAvailableModels] = useState<ChatModel[]>(FALLBACK_MODELS);
    const [initialPrompt, setInitialPrompt] = useState<string | null>(null);
    const [routePath, setRoutePath] = useState(() =>
        typeof window !== 'undefined' ? window.location.pathname : '/'
    );
    const [activeMind, setActiveMind] = useState<Mind | null>(null);
    const [pinnedMinds, setPinnedMinds] = useState<Mind[]>([]);

    const { isSettingsView, clearHash } = useURLRouter();
    const { isAuthenticated, loading: isAuthLoading, user } = useAuth();
    const { settings } = useSettings();
    const { t } = useTranslation();

    const {
        history,
        canvasTextdoc,
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
        updateCanvasTextdocContent,
        updateBeatboxState,
        sessionAccess,
        isReadOnly,
        isTemporaryChat,
        sessionActivity,
        optimisticSessions,
        markSessionActivitySeen,
        startTemporaryChat,
        enableSharing,
        disableSharing,
    } = useChat();

    const { sessions, refreshSessions, removeSession, onSessionRenamed } = useSessionList({
        isAuthenticated,
        allowGuestChatsSave: ALLOW_GUEST_CHATS_SAVE,
    });

    const isRailExpanded = isMobileViewport ? isMobileRailOpen : isRailExpandedDesktop;
    const selectedModel = isAuthLoading || isModelAvailable(currentModel, availableModels)
        ? currentModel
        : getFallbackModelId(availableModels);
    const visibleSessions = useMemo<SessionSummary[]>(() => {
        const byId = new Map<string, SessionSummary>(sessions.map((session) => [session.session_id, session]));
        Object.values(optimisticSessions as Record<string, SessionSummary>).forEach((session) => {
            if (session?.session_id && !byId.has(session.session_id)) {
                byId.set(session.session_id, session);
            }
        });
        return Array.from(byId.values()).sort(
            (a, b) => (Number(b.last_updated) || 0) - (Number(a.last_updated) || 0)
        );
    }, [optimisticSessions, sessions]);

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
        let cancelled = false;

        void apiService
            .listModels()
            .then((models) => {
                if (!cancelled) {
                    setAvailableModels(normalizeModelOptions(models));
                }
            })
            .catch((error) => {
                console.warn('Failed to load model catalog:', error);
                if (!cancelled) {
                    setAvailableModels(FALLBACK_MODELS);
                }
            });

        return () => {
            cancelled = true;
        };
    }, [isAuthenticated, user?.id]);

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
    const loadingSessionIdRef = useRef<string | null>(null);
    const notifyOnDoneRef = useRef(false);
    const canvasWidthRef = useRef(canvasWidth);

    useEffect(() => {
        canvasWidthRef.current = canvasWidth;
    }, [canvasWidth]);

    useEffect(() => {
        const wasLoading = wasLoadingRef.current;
        const previousLoadingSessionId = loadingSessionIdRef.current;
        wasLoadingRef.current = isLoading;
        loadingSessionIdRef.current = isLoading ? currentSessionId : null;

        if (wasLoading && !isLoading && previousLoadingSessionId && previousLoadingSessionId === currentSessionId) {
            if (settings.notifyOnThinkingDone && notifyOnDoneRef.current) {
                notifyThinkingDone();
                notifyOnDoneRef.current = false;
            }
            if (currentSessionId && !isTemporaryChat) {
                setTimeout(() => refreshSessions(), 0);
            }
        }
    }, [currentSessionId, isLoading, isTemporaryChat, refreshSessions, settings.notifyOnThinkingDone]);

    const sessionActivityRefreshRef = useRef('');

    useEffect(() => {
        const completedKey = Object.entries(sessionActivity)
            .filter(([, activity]) => {
                const typedActivity = activity as ChatSessionActivity;
                return typedActivity?.status && typedActivity.status !== 'generating';
            })
            .map(([sessionId, activity]) => {
                const typedActivity = activity as ChatSessionActivity;
                return `${sessionId}:${typedActivity.status}:${typedActivity.updatedAt}`;
            })
            .join('|');

        if (!completedKey || completedKey === sessionActivityRefreshRef.current) {
            return;
        }

        sessionActivityRefreshRef.current = completedKey;
        setTimeout(() => refreshSessions(), 0);
    }, [refreshSessions, sessionActivity]);

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
            setInitialPrompt(null);
            const path = window.location.pathname;
            if (!isTemporaryChat && (path === '/' || !path.startsWith('/c/'))) {
                clearChat({ historyMode: 'none' });
            }

            notifyOnDoneRef.current = true;
            sendMessage(text, files, selectedModel, {
                ...options,
                mindId: activeMind?.public_id || null,
            });
        },
        [activeMind, clearChat, isTemporaryChat, sendMessage, selectedModel]
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

        const authView = params.get('auth');
        if (authView && !isAuthLoading) {
            if (!isAuthenticated && (authView === 'login' || authView === 'register')) {
                setTimeout(() => setAuthOpen(authView), 0);
            }
            shouldUpdateURL = true;
        }

        if (params.has('github') || params.has('github_error')) {
            shouldUpdateURL = true;
        }

        if (shouldUpdateURL && params.toString()) {
            const cleanURL = `${window.location.pathname}${window.location.hash}`;
            window.history.replaceState(null, '', cleanURL);
        }
    }, [handleSendMessage, isAuthenticated, isAuthLoading]);

    useEffect(() => {
        setTimeout(() => refreshSessions(), 0);
    }, [refreshSessions]);

    useEffect(() => {
        if (currentSessionId && !isTemporaryChat) {
            setTimeout(() => refreshSessions(), 0);
        }
    }, [currentSessionId, isTemporaryChat, refreshSessions]);

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
                markSessionActivitySeen(id);
                setMobileRailOpen(false);
                return;
            }
            markSessionActivitySeen(id);
            setActiveMind(null);
            void loadSession(id, { historyMode: 'push' }).then((data) => {
                if (data) {
                    setActiveMind(data.mind || null);
                }
            });
            setMobileRailOpen(false);
        },
        [currentSessionId, loadSession, markSessionActivitySeen]
    );

    const handleNewChat = useCallback(() => {
        notifyOnDoneRef.current = false;
        setActiveMind(null);
        clearChat({ historyMode: 'push' });
        setRoutePath('/');
        setMobileRailOpen(false);
    }, [clearChat]);

    const handleTemporaryChat = useCallback(() => {
        notifyOnDoneRef.current = false;
        setActiveMind(null);
        setShareModalOpen(false);
        startTemporaryChat({ historyMode: 'push' });
        setRoutePath('/');
        setMobileRailOpen(false);
    }, [startTemporaryChat]);

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

    const handleAdminClick = useCallback(() => {
        clearChat({ historyMode: 'none' });
        navigateTo('/admin');
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
    const isAdminRoute = routePath === '/admin' || routePath.startsWith('/admin/');
    const isChatSurface = !isMindsRoute && !isEditorRoute && !isAdminRoute;
    const showTemporaryChatButton = routePath === '/' && history.length === 0 && !isTemporaryChat;
    const canvasTextdocVersion = canvasTextdoc
        ? `${canvasTextdoc.id || ''}:${canvasTextdoc.updated_at || 0}`
        : '';

    useEffect(() => {
        const frame = window.requestAnimationFrame(() => {
            if (!canvasTextdoc) {
                setCanvasVisible(false);
                setSelectedCanvasTextdoc(null);
                return;
            }

            if (isCanvasVisible) {
                setSelectedCanvasTextdoc((current) => {
                    if (!current || current.id === canvasTextdoc.id || current.name === canvasTextdoc.name) {
                        return canvasTextdoc;
                    }
                    return current;
                });
            }
        });

        return () => window.cancelAnimationFrame(frame);
    }, [canvasTextdoc, canvasTextdocVersion, isCanvasVisible]);

    const activeCanvasTextdoc = selectedCanvasTextdoc || canvasTextdoc;
    const canvasDockTextdoc = activeCanvasTextdoc || canvasTextdoc;

    const handleOpenCanvas = useCallback((textdoc: CanvasTextdoc) => {
        setSelectedCanvasTextdoc(textdoc);
        setCanvasVisible(true);
    }, []);

    const handleCanvasContentChange = useCallback((content: string) => {
        const targetId = activeCanvasTextdoc?.id || null;
        setSelectedCanvasTextdoc((current) => current
            ? { ...current, content, updated_at: Math.floor(Date.now() / 1000) }
            : current
        );
        updateCanvasTextdocContent(content, targetId);
    }, [activeCanvasTextdoc?.id, updateCanvasTextdocContent]);

    const updateCanvasWidth = useCallback((nextWidth: number) => {
        const clampedWidth = clampCanvasWidth(nextWidth);
        canvasWidthRef.current = clampedWidth;
        setCanvasWidth(clampedWidth);
    }, []);

    useEffect(() => {
        const handleResize = () => {
            updateCanvasWidth(canvasWidthRef.current);
        };

        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, [updateCanvasWidth]);

    const handleCanvasResizeStart = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
        event.preventDefault();
        setCanvasResizing(true);
        event.currentTarget.setPointerCapture?.(event.pointerId);
    }, []);

    const handleCanvasResizeKeyDown = useCallback((event: ReactKeyboardEvent<HTMLDivElement>) => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') {
            return;
        }
        event.preventDefault();
        const step = event.shiftKey ? 48 : 16;
        const direction = event.key === 'ArrowLeft' ? 1 : -1;
        const nextWidth = clampCanvasWidth(canvasWidthRef.current + direction * step);
        setCanvasWidth(nextWidth);
        window.localStorage.setItem(CANVAS_WIDTH_STORAGE_KEY, String(nextWidth));
    }, []);

    useEffect(() => {
        if (!isCanvasResizing) {
            return undefined;
        }

        const handlePointerMove = (event: PointerEvent) => {
            updateCanvasWidth(window.innerWidth - event.clientX);
        };

        const handlePointerUp = () => {
            setCanvasResizing(false);
            window.localStorage.setItem(CANVAS_WIDTH_STORAGE_KEY, String(canvasWidthRef.current));
        };

        window.addEventListener('pointermove', handlePointerMove);
        window.addEventListener('pointerup', handlePointerUp, { once: true });
        window.addEventListener('pointercancel', handlePointerUp, { once: true });

        return () => {
            window.removeEventListener('pointermove', handlePointerMove);
            window.removeEventListener('pointerup', handlePointerUp);
            window.removeEventListener('pointercancel', handlePointerUp);
        };
    }, [isCanvasResizing, updateCanvasWidth]);

    useLayoutEffect(() => {
        const shouldShowCanvasDock = Boolean(canvasDockTextdoc && isChatSurface);
        document.documentElement.classList.toggle('has-canvas-dock', shouldShowCanvasDock);
        document.documentElement.classList.toggle('canvas-open', shouldShowCanvasDock && isCanvasVisible);
        document.documentElement.classList.toggle('canvas-resizing', isCanvasResizing);
        document.body.classList.toggle('has-canvas-dock', shouldShowCanvasDock);
        document.body.classList.toggle('canvas-open', shouldShowCanvasDock && isCanvasVisible);
        document.body.classList.toggle('canvas-resizing', isCanvasResizing);
        if (shouldShowCanvasDock) {
            document.body.style.setProperty('--canvas-panel-width', `${canvasWidth}px`);
        } else {
            document.body.style.removeProperty('--canvas-panel-width');
        }
        return () => {
            document.documentElement.classList.remove('has-canvas-dock');
            document.documentElement.classList.remove('canvas-open');
            document.documentElement.classList.remove('canvas-resizing');
            document.body.classList.remove('has-canvas-dock');
            document.body.classList.remove('canvas-open');
            document.body.classList.remove('canvas-resizing');
            document.body.style.removeProperty('--canvas-panel-width');
        };
    }, [canvasDockTextdoc, canvasWidth, isCanvasResizing, isCanvasVisible, isChatSurface]);

    const canvasDockIsCode = canvasDockTextdoc?.type?.startsWith('code/') ?? false;
    const canvasDockLanguage = canvasDockIsCode ? canvasDockTextdoc?.type.slice('code/'.length) : '';
    const canvasDockTypeLabel = canvasDockTextdoc
        ? (canvasDockIsCode
            ? t('canvas.type.code', { language: canvasDockLanguage })
            : t('canvas.type.document'))
        : '';
    const canvasDockLineCount = canvasDockTextdoc
        ? (canvasDockTextdoc.content || '').split(/\r\n|\r|\n/).length
        : 0;

    return (
        <>
            <SEOHelmet />

            {isAuthenticated && (
                <Suspense fallback={null}>
                    <AppRail
                        isExpanded={isRailExpanded}
                        onToggle={handleRailToggle}
                        sessions={visibleSessions}
                        sessionActivity={sessionActivity}
                        currentSessionId={currentSessionId}
                        onSelectSession={handleSelectSession}
                        onNewChat={handleNewChat}
                        onMindsClick={handleMindsClick}
                        onAdminClick={handleAdminClick}
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

            <div className="ui-app-canvas-stage">
                <main className="ui-app-main-shell">
                    <GlobalHeader
                        isAuthenticated={isAuthenticated}
                        onMenuToggle={handleRailToggle}
                        currentModel={selectedModel}
                        models={availableModels}
                        onModelChange={setCurrentModel}
                        onOpenAuth={() => setAuthOpen('login')}
                        onShowRegister={() => setAuthOpen('register')}
                        shareInfo={isTemporaryChat ? null : sessionAccess}
                        currentSessionId={isTemporaryChat ? null : currentSessionId}
                        isReadOnly={isReadOnly}
                        onOpenShareModal={() => setShareModalOpen(true)}
                        onNewChat={handleNewChat}
                        onTemporaryChat={handleTemporaryChat}
                        isTemporaryChat={isTemporaryChat}
                        showChatControls={isChatSurface}
                        showTemporaryChatButton={showTemporaryChatButton}
                    />

                    {isAdminRoute ? (
                        <Suspense fallback={null}>
                            <AdminPanel
                                isAuthenticated={isAuthenticated}
                                onOpenAuth={() => setAuthOpen('login')}
                            />
                        </Suspense>
                    ) : isMindsRoute ? (
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
                                {isTemporaryChat && (
                                    <p className="ui-landing-temporary-note">
                                        <LockKeyhole size={15} aria-hidden="true" />
                                        <span>{t('temporaryChat.description')}</span>
                                    </p>
                                )}
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
                                    onInitialPromptConsumed={() => setInitialPrompt(null)}
                                    onOpenAuth={() => setAuthOpen('login')}
                                />
                            </LandingHero>
                        </div>
                    ) : (
                        <Suspense fallback={null}>
                            <>
                                {isTemporaryChat && (
                                    <div className="ui-chat-mind-banner" role="status">
                                        <div className="ui-chat-mind-banner-main">
                                            <div className="ui-chat-mind-banner-icon" aria-hidden="true">
                                                <LockKeyhole size={19} />
                                            </div>
                                            <div className="ui-chat-mind-banner-copy">
                                                <span>{t('temporaryChat.badge')}</span>
                                                <strong>{t('temporaryChat.title')}</strong>
                                                <p>{t('temporaryChat.description')}</p>
                                            </div>
                                        </div>
                                    </div>
                                )}
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
                                    currentSessionId={isTemporaryChat ? null : currentSessionId}
                                    isReadOnly={isReadOnly}
                                    onRegenerate={(messageId) => {
                                        if (regenerateMessage) {
                                            notifyOnDoneRef.current = true;
                                            regenerateMessage(messageId, selectedModel);
                                        }
                                    }}
                                    onEdit={(messageId, newText) => {
                                        if (editMessage) {
                                            notifyOnDoneRef.current = true;
                                            editMessage(messageId, newText, selectedModel);
                                        }
                                    }}
                                    onSwitchVariant={(messageId, direction) => {
                                        if (switchVariant) {
                                            switchVariant(messageId, direction);
                                        }
                                    }}
                                    onBeatboxStateChange={updateBeatboxState}
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
                                    onInitialPromptConsumed={() => setInitialPrompt(null)}
                                    onOpenAuth={() => setAuthOpen('login')}
                                />
                            </>
                        </Suspense>
                    )}
                </main>

                {isChatSurface && canvasDockTextdoc && (
                    <aside
                        className={isCanvasVisible ? 'chat-canvas-dock is-open' : 'chat-canvas-dock is-collapsed'}
                        aria-label={t('canvas.ariaLabel')}
                        style={{ '--canvas-panel-width': `${canvasWidth}px` } as CSSProperties}
                    >
                        {isCanvasVisible ? (
                            <>
                                <div
                                    className="chat-canvas-resize-handle"
                                    role="separator"
                                    aria-orientation="vertical"
                                    aria-label={t('canvas.resizeHandle')}
                                    tabIndex={0}
                                    onPointerDown={handleCanvasResizeStart}
                                    onKeyDown={handleCanvasResizeKeyDown}
                                />
                                <Suspense fallback={null}>
                                    <CanvasPanel
                                        textdoc={canvasDockTextdoc}
                                        onClose={() => setCanvasVisible(false)}
                                        onContentChange={handleCanvasContentChange}
                                    />
                                </Suspense>
                            </>
                        ) : (
                            <button
                                type="button"
                                className="chat-canvas-dock-trigger"
                                onClick={() => handleOpenCanvas(canvasDockTextdoc)}
                                aria-label={t('canvas.card.openAria', { name: canvasDockTextdoc.name })}
                                title={t('canvas.card.openAria', { name: canvasDockTextdoc.name })}
                            >
                                <span className="chat-canvas-dock-icon" aria-hidden="true">
                                    {canvasDockIsCode ? <FileCode2 size={18} /> : <FileText size={18} />}
                                </span>
                                <span className="chat-canvas-dock-copy">
                                    <span>{t('canvas.badge')}</span>
                                    <strong>{canvasDockTextdoc.name}</strong>
                                    <small>{canvasDockTypeLabel} / {t('canvas.lines', { count: canvasDockLineCount })}</small>
                                </span>
                                <PanelRightOpen size={17} aria-hidden="true" />
                            </button>
                        )}
                    </aside>
                )}
            </div>

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
                        currentModel={selectedModel}
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
