import { sessionContextUsage } from './features/chat/contextUsage';
import type { ComposerToolOption } from './services/api';
import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type {
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from 'react';
import { BadgeCheck, BrainCircuit, FileCode2, FileText, LockKeyhole, Settings2, X } from 'lucide-react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { useTranslation } from 'react-i18next';
import { SettingsProvider, useSettings } from './context/SettingsContext';
import LandingHero from './components/Chat/LandingHero';
import InputArea from './components/Chat/InputArea';
import { maxChatReferences, type ChatReference } from './features/chat/ChatReferencePicker';
import SEOHelmet from './components/UI/SEOHelmet';
import Pet from './components/UI/Pet';
import {
  apiService,
  type CanvasTextdoc,
  type Mind,
  type ModelSpeed,
  type ThinkingLevel,
} from './services/api';
import { useChat } from './hooks/useChat';
import { useURLRouter } from './hooks/useURLRouter';
import { notifyThinkingDone } from './utils/notifications';
import { ALLOW_GUEST_CHATS_SAVE } from './utils/constants';
import GlobalHeader from './features/chat/components/GlobalHeader';
import { useChatPet } from './features/chat/useChatPet';
import {
  FALLBACK_MODELS,
  getFallbackModelId,
  isImageToolModel,
  normalizeModelOptions,
  normalizeThinkingLevel,
  type ChatModel,
} from './features/chat/modelSelection';
import { useSessionList, type SessionSummary } from './features/sessions/hooks/useSessionList';
import { useProjects } from './features/projects/useProjects';
import { projectIdForPath, projectPath } from './features/projects/projectNavigation';
import ProjectRecentChats from './features/projects/ProjectRecentChats';
import { useSessionModelSelection, type ChatModelPreference } from './features/chat/useSessionModelSelection';
import { showToast } from './utils/toast';
import type { CanvasHtmlPreviewHandle } from './features/canvas/CanvasHtmlPreview';
import {
  clearGuestChatTransfer,
  hasPendingGuestChatTransfer,
  prepareGuestChatTransferHistory,
  readGuestChatTransfer,
  stageGuestChatTransfer,
} from './services/guestChatTransfer';

type AuthModalState = false | 'login' | 'register' | 'link';

type ChatSessionActivity = {
  status?: 'generating' | 'complete' | 'error';
  updatedAt?: number;
};

type WindowWithLayoutModals = Window & {
  openImageLightbox?: (
    imageSrc: string,
    messageId?: string,
    options?: { canRegenerate?: boolean; downloadName?: string }
  ) => void;
  closeImageLightbox?: () => void;
};

interface ImageLightboxState {
  isOpen: boolean;
  imageSrc: string | null;
  messageId: string | null;
  canRegenerate: boolean;
  downloadName: string | null;
}

const MOBILE_RAIL_MEDIA_QUERY = '(max-width: 1024px)';
const CANVAS_WIDTH_STORAGE_KEY = 'remind.canvas.width';
const THINKING_LEVEL_STORAGE_KEY = 'remind.chat.thinkingLevel';
const CANVAS_MIN_WIDTH = 360;
const CANVAS_DEFAULT_WIDTH = 520;
const CANVAS_MAX_WIDTH = 820;
const AppRail = lazy(() => import('./components/Layout/AppRail'));
const ChatContainer = lazy(() => import('./components/Chat/ChatContainer'));
const SettingsModal = lazy(() => import('./components/Modals/SettingsModal'));
const ProjectDetailsModal = lazy(() => import('./features/projects/ProjectDetailsModal'));
const ContextCheckpointModal = lazy(() => import('./features/chat/ContextCheckpointModal'));
const AuthModal = lazy(() => import('./components/Modals/AuthModal'));
const ImageLightbox = lazy(() => import('./components/Modals/ImageLightbox'));
const ShareModal = lazy(() => import('./features/share/components/ShareModal'));
const MindsPage = lazy(() => import('./features/minds/MindsPage'));
const AutomationPage = lazy(() => import('./features/automations/AutomationPage'));
const PluginsPage = lazy(() => import('./features/plugins/PluginsPage'));
const MindEditorPage = lazy(() => import('./features/minds/MindEditorPage'));
const AdminPanel = lazy(() => import('./features/admin/AdminPanel'));
const CanvasPanel = lazy(() => import('./features/canvas/CanvasPanel'));
const CanvasHtmlPreview = lazy(() => import('./features/canvas/CanvasHtmlPreview'));

function clampCanvasWidth(width: number): number {
  if (typeof window === 'undefined') {
    return Math.min(CANVAS_MAX_WIDTH, Math.max(CANVAS_MIN_WIDTH, width));
  }

  const railOffset =
    Number.parseFloat(
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
  const [projectDetailsId, setProjectDetailsId] = useState<string | null>(null);
  const [contextSessionId, setContextSessionId] = useState<string | null>(null);
  const [referenceDraft, setReferenceDraft] = useState<{ scope: string; choices: ChatReference[] }>({ scope: '', choices: [] });
  const [isAuthOpen, setAuthOpen] = useState<AuthModalState>(false);
  const [imageLightbox, setImageLightbox] = useState<ImageLightboxState>({
    isOpen: false,
    imageSrc: null,
    messageId: null,
    canRegenerate: true,
    downloadName: null,
  });
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [isCanvasVisible, setCanvasVisible] = useState(false);
  const [isCanvasPreviewVisible, setCanvasPreviewVisible] = useState(false);
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
  const [modelChoices, setModelChoices] = useState<Record<string, ChatModelPreference>>({});
  const [legacyGuestEffort] = useState(() => {
    if (typeof window === 'undefined') {
      return null;
    }
    const stored = window.localStorage.getItem(THINKING_LEVEL_STORAGE_KEY);
    return stored ? normalizeThinkingLevel(stored) : null;
  });
  const [availableTools, setAvailableTools] = useState<ComposerToolOption[]>([]);
  const [availableModels, setAvailableModels] = useState<ChatModel[]>(FALLBACK_MODELS);
  const [initialPrompt, setInitialPrompt] = useState<string | null>(null);
  const [routePath, setRoutePath] = useState(() =>
    typeof window !== 'undefined' ? window.location.pathname : '/'
  );
  const [activeMind, setActiveMind] = useState<Mind | null>(null);
  const [pinnedMinds, setPinnedMinds] = useState<Mind[]>([]);
  const mobileRailReturnFocusRef = useRef<HTMLElement | null>(null);

  const { isSettingsView, clearHash } = useURLRouter();
  const { isAuthenticated, loading: isAuthLoading, user } = useAuth();
  const { settings } = useSettings();
  const selectionOwner = user?.id || 0;
  const profileSelection =
    settings.agentSelection?.owner === selectionOwner ? settings.agentSelection : null;
  const { t } = useTranslation();

  const {
    history,
    canvasTextdoc,
    isLoading,
    isCanvasStreaming,
    sendMessage,
    compactSession,
    compactingSessions,
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
    sessionProject,
    isReadOnly,
    isTemporaryChat,
    connectionState,
    queuedMessageCount,
    sessionActivity,
    generationOutcome,
    optimisticSessions,
    markSessionActivitySeen,
    startTemporaryChat,
    enableSharing,
    disableSharing,
    buildHistoryForAPI,
  } = useChat();

  const chatPetState = useChatPet(
    history,
    isLoading,
    currentSessionId,
    generationOutcome,
    isCanvasStreaming ? canvasTextdoc?.type : undefined
  );
  const petState = currentSessionId && compactingSessions.has(currentSessionId) ? 'learning' : chatPetState;

  const projectStore = useProjects(isAuthenticated ? user?.id : undefined);
  const { sessions, refreshSessions, removeSession, onSessionRenamed, onSessionMoved } = useSessionList({
    isAuthenticated,
    allowGuestChatsSave: ALLOW_GUEST_CHATS_SAVE,
  });

  const desktopRailExpanded = isRailExpandedDesktop;
  const isRailExpanded = isMobileViewport ? isMobileRailOpen : desktopRailExpanded;
  const activeSessionRow = sessions.find((row) => row.session_id === currentSessionId);
  const persistedWebChat = Boolean(
    (activeSessionRow && (!activeSessionRow.source || activeSessionRow.source === 'web')) ||
    (!activeSessionRow && sessionAccess?.isOwner)
  );
  const savedModel = useSessionModelSelection(
    selectionOwner,
    currentSessionId,
    isAuthenticated && !isTemporaryChat && !isReadOnly && persistedWebChat,
    generationOutcome?.sessionId === currentSessionId ? generationOutcome.finishedAt : undefined
  );
  const modelChoiceKey = `${selectionOwner}:${currentSessionId || 'new'}`;
  const currentChoice = modelChoices[modelChoiceKey] || savedModel.choice;
  const historyModel = history.findLast((message) =>
    message.role === 'model' && typeof message.modelId === 'string'
      && !isImageToolModel({ id: message.modelId })
  )?.modelId;
  const requestedModel = currentChoice?.model || historyModel || profileSelection?.model || '';
  const selectedModel =
    requestedModel || getFallbackModelId(availableModels.filter((model) => !isImageToolModel(model)));
  const changeModelOptions = (choice: ChatModelPreference) => {
    setModelChoices((choices) => ({
      ...choices,
      [modelChoiceKey]: choice,
    }));
    void savedModel.save(choice)?.then((saved) => {
      if (!saved) return;
      setModelChoices((choices) => {
        if (choices[modelChoiceKey] !== choice) return choices;
        const next = { ...choices };
        delete next[modelChoiceKey];
        return next;
      });
    });
  };
  const chooseModel = (model: string) => {
    if (model !== selectedModel) changeModelOptions({ model });
  };
  const currentContextUsage = useMemo(
    () => sessionContextUsage(history, selectedModel),
    [history, selectedModel]
  );
  const selectedModelDefinition = availableModels.find((model) => model.id === selectedModel);
  const modelUnavailable = Boolean(selectedModel) && !selectedModelDefinition && availableModels.length > 0;
  const chosenSpeed = currentChoice
    ? currentChoice.serviceTier || 'standard'
    : (profileSelection?.speeds?.[selectedModel] as ModelSpeed) || 'standard';
  const selectedSpeed = selectedModelDefinition?.serviceTiers.includes(chosenSpeed)
    ? chosenSpeed
    : 'standard';
  const mindTools = availableTools.filter(
    (tool) =>
      (!activeMind?.skill_ids || activeMind.skill_ids.includes(tool.id)) &&
      !(tool.id === 'slides' && isTemporaryChat)
  );
  const preferredEffort = currentChoice
    ? currentChoice.thinkingLevel
    : profileSelection?.efforts?.[selectedModel] || (!isAuthenticated ? legacyGuestEffort : null);
  const selectedThinkingLevel = preferredEffort && selectedModelDefinition?.thinkingLevels.includes(preferredEffort)
    ? preferredEffort : undefined;
  const chooseSpeed = (speed: ModelSpeed) => {
    changeModelOptions({
      model: selectedModel,
      ...(selectedThinkingLevel ? { thinkingLevel: selectedThinkingLevel } : {}),
      ...(speed === 'standard' ? {} : { serviceTier: speed }),
    });
  };
  const chooseEffort = (level: ThinkingLevel | null) => {
    changeModelOptions({
      model: selectedModel,
      ...(level ? { thinkingLevel: level } : {}),
      ...(selectedSpeed !== 'standard' ? { serviceTier: selectedSpeed } : {}),
    });
  };
  const visibleSessions = useMemo<SessionSummary[]>(() => {
    const byId = new Map<string, SessionSummary>(
      sessions.map((session) => [session.session_id, session])
    );
    Object.values(optimisticSessions as Record<string, SessionSummary>).forEach((session) => {
      if (session?.session_id && !byId.has(session.session_id)) {
        byId.set(session.session_id, session);
      }
    });
    return Array.from(byId.values()).sort(
      (a, b) => (Number(b.last_updated) || 0) - (Number(a.last_updated) || 0)
    );
  }, [optimisticSessions, sessions]);
  const projectRouteId = projectIdForPath(routePath);
  const projectDetails = projectStore.projects.find((project) => project.id === projectDetailsId);
  const routedProject = projectStore.projects.find((project) => project.id === projectRouteId);
  const chatProjectId = activeSessionRow?.workspace_id !== undefined
    ? activeSessionRow.workspace_id
    : sessionProject?.sessionId === currentSessionId
      ? sessionProject.id
      : null;
  const activeProjectId = projectRouteId || chatProjectId;
  const activeProject = projectStore.projects.find((project) => project.id === activeProjectId)
    || (sessionProject?.sessionId === currentSessionId && sessionProject.id === activeProjectId
      ? sessionProject : undefined);

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
    let revision = 0;
    const refreshCatalog = () => {
      const currentRevision = ++revision;
      void apiService
        .listModelCatalog()
        .then(({ models, tools }) => {
          if (!cancelled && revision === currentRevision) {
            setAvailableModels(normalizeModelOptions(models));
            setAvailableTools(tools);
          }
        })
        .catch((error) => console.warn('Failed to load model catalog:', error));
    };
    refreshCatalog();
    window.addEventListener('focus', refreshCatalog);
    window.addEventListener('remind:model-catalog', refreshCatalog);
    return () => {
      cancelled = true;
      window.removeEventListener('focus', refreshCatalog);
      window.removeEventListener('remind:model-catalog', refreshCatalog);
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
    const isDesktopRailOpen = hasDesktopRail && desktopRailExpanded;
    const isMobileOverlayOpen = !!isAuthenticated && isMobileViewport && !!isMobileRailOpen;

    document.body.classList.toggle('has-rail', hasDesktopRail);
    document.body.classList.toggle('rail-open', isDesktopRailOpen);
    document.body.classList.toggle('mobile-menu-open', isMobileOverlayOpen);
  }, [isAuthenticated, isMobileViewport, isMobileRailOpen, desktopRailExpanded]);

  useEffect(() => {
    if (!isAuthenticated || !isMobileViewport || !isMobileRailOpen) {
      return undefined;
    }

    const rail = document.getElementById('appRail');
    if (!rail) {
      return undefined;
    }

    const activeElement = document.activeElement;
    if (activeElement instanceof HTMLElement && !rail.contains(activeElement)) {
      mobileRailReturnFocusRef.current = activeElement;
    }

    const getFocusableElements = () =>
      Array.from(
        rail.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
        )
      ).filter((element) => !element.hasAttribute('hidden'));

    const frame = window.requestAnimationFrame(() => {
      rail.querySelector<HTMLElement>('[data-rail-close]')?.focus();
    });

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setMobileRailOpen(false);
        return;
      }

      if (event.key !== 'Tab') {
        return;
      }

      const focusableElements = getFocusableElements();
      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      if (!firstElement || !lastElement) {
        event.preventDefault();
        return;
      }

      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener('keydown', handleKeyDown);
      const returnTarget = mobileRailReturnFocusRef.current;
      mobileRailReturnFocusRef.current = null;
      if (returnTarget?.isConnected) {
        window.requestAnimationFrame(() => returnTarget.focus());
      }
    };
  }, [isAuthenticated, isMobileRailOpen, isMobileViewport]);

  useEffect(() => {
    return () => {
      document.body.classList.remove('has-rail');
      document.body.classList.remove('rail-open');
      document.body.classList.remove('mobile-menu-open');
    };
  }, []);

  useEffect(() => {
    const appWindow = window as WindowWithLayoutModals;

    appWindow.openImageLightbox = (imageSrc, messageId, options) => {
      setImageLightbox({
        isOpen: true,
        imageSrc,
        messageId: messageId ?? null,
        canRegenerate: options?.canRegenerate !== false,
        downloadName: options?.downloadName ?? null,
      });
    };
    appWindow.closeImageLightbox = () => {
      setImageLightbox({
        isOpen: false,
        imageSrc: null,
        messageId: null,
        canRegenerate: true,
        downloadName: null,
      });
    };

    return () => {
      delete appWindow.openImageLightbox;
      delete appWindow.closeImageLightbox;
    };
  }, []);

  const wasLoadingRef = useRef(false);
  const loadingSessionIdRef = useRef<string | null>(null);
  const notifyOnDoneRef = useRef(false);
  const canvasWidthRef = useRef(canvasWidth);
  const canvasPreviewRef = useRef<CanvasHtmlPreviewHandle | null>(null);
  const canvasSaveTimerRef = useRef<number | null>(null);
  const guestChatImportStartedRef = useRef(false);

  useEffect(() => {
    canvasWidthRef.current = canvasWidth;
  }, [canvasWidth]);

  useEffect(() => {
    const wasLoading = wasLoadingRef.current;
    const previousLoadingSessionId = loadingSessionIdRef.current;
    wasLoadingRef.current = isLoading;
    loadingSessionIdRef.current = isLoading ? currentSessionId : null;

    if (
      wasLoading &&
      !isLoading &&
      previousLoadingSessionId &&
      previousLoadingSessionId === currentSessionId
    ) {
      if (settings.notifyOnThinkingDone && notifyOnDoneRef.current) {
        notifyThinkingDone();
        notifyOnDoneRef.current = false;
      }
      if (currentSessionId && !isTemporaryChat) {
        setTimeout(() => refreshSessions(), 0);
      }
    }
  }, [
    currentSessionId,
    isLoading,
    isTemporaryChat,
    refreshSessions,
    settings.notifyOnThinkingDone,
  ]);

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
      const legacyWorkspace = window.location.pathname === '/workspace';
      const path = legacyWorkspace ? '/' : normalizeAppPath(window.location.pathname);
      if (path !== window.location.pathname) {
        window.history.replaceState(
          {},
          '',
          `${path}${window.location.search}${legacyWorkspace ? '#settings/workspace' : window.location.hash}`
        );
        if (legacyWorkspace) window.dispatchEvent(new Event('hashchange'));
      }
      setRoutePath(path);
      if (path.startsWith('/c/')) {
        const slug = decodeURIComponent(path.split('/c/')[1]);
        if (slug) {
          setActiveMind(null);
          if (isAuthenticated && hasPendingGuestChatTransfer(slug)) {
            return;
          }
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
      setActiveMind(null);
      clearChat({ historyMode: 'none' });
    };

    handleRouteChange();
    window.addEventListener('popstate', handleRouteChange);

    return () => window.removeEventListener('popstate', handleRouteChange);
  }, [loadSession, clearChat, isAuthenticated]);

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
    (
      text: string,
      files: File[],
      options: {
        composerContent?: string;
        chatReferences?: ChatReference[];
        tools?: string[];
        webSearch?: boolean;
        autoWebSearch?: boolean;
      } = {}
    ) => {
      setInitialPrompt(null);
      if (modelUnavailable && !(text.trim() === '/compact' && files.length === 0)) {
        showToast(t('agentSettings.modelUnavailable'), { type: 'error' });
        return;
      }
      const path = window.location.pathname;
      const projectId = projectIdForPath(path);
      if (projectId && (!routedProject || routedProject.id !== projectId)) return;
      if (!isTemporaryChat && (path === '/' || !path.startsWith('/c/'))) {
        clearChat({ historyMode: 'none' });
      }

      notifyOnDoneRef.current = true;
      sendMessage(text, files, selectedModel, {
        ...options,
        mindId: activeMind?.public_id || null,
        _sessionMind: activeMind || null,
        ...(selectedThinkingLevel ? { thinkingLevel: selectedThinkingLevel } : {}),
        serviceTier: selectedSpeed,
        ...(projectId && routedProject ? { project: routedProject } : {}),
      });
      if (path !== window.location.pathname) {
        setRoutePath(normalizeAppPath(window.location.pathname));
      }
    },
    [
      activeMind,
      clearChat,
      isTemporaryChat,
      selectedModel,
      selectedThinkingLevel,
      selectedSpeed,
      sendMessage,
      modelUnavailable,
      routedProject,
      t,
    ]
  );

  const modelForMessage = (messageId: string | null, editing = false) => {
    const index = history.findIndex((message) => message.id === messageId);
    const message = history[index + (editing ? 1 : 0)];
    const imageModel = availableModels.find(
      (model) => model.id === message?.modelId && isImageToolModel(model)
    );
    return imageModel?.id || selectedModel;
  };

  const handleRepairPython = useCallback(
    (error: string, code: string) => {
      const repairPrompt = t('canvas.pythonTerminal.repairPrompt', {
        error,
        code,
        interpolation: { escapeValue: false },
      });
      handleSendMessage(repairPrompt, [], {});
    },
    [handleSendMessage, t]
  );

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    let shouldUpdateURL = false;

    const prompt = params.get('prompt');
    if (prompt) {
      const decodedPrompt = decodeURIComponent(prompt);
      setTimeout(() => {
        setInitialPrompt(decodedPrompt);
        if (
          params.get('auto_send') === 'true' &&
          !projectIdForPath(window.location.pathname) &&
          !/^(chatgpt|codex|key)\//.test(params.get('model') || selectedModel)
        ) {
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
      setTimeout(
        () => setModelChoices((choices) => ({ ...choices, [modelChoiceKey]: { model: decodeURIComponent(model) } })),
        0
      );
      shouldUpdateURL = true;
    }

    const authView = params.get('auth');
    if (authView && !isAuthLoading) {
      if (authView === 'login' || authView === 'register' || authView === 'link') {
        const target = authView === 'link' && isAuthenticated ? 'link' : 'login';
        setTimeout(() => setAuthOpen(target), 0);
      }
      shouldUpdateURL = true;
    }

    const authError = params.get('auth_error');
    if (authError && /^[a-z_]{1,64}$/.test(authError)) {
      window.sessionStorage.setItem('remind.auth.error', authError);
      shouldUpdateURL = true;
    }

    if (params.has('github') || params.has('github_error')) {
      shouldUpdateURL = true;
    }

    if (shouldUpdateURL && params.toString()) {
      const cleanURL = `${window.location.pathname}${window.location.hash}`;
      window.history.replaceState(null, '', cleanURL);
    }
  }, [handleSendMessage, isAuthenticated, isAuthLoading, selectedModel, modelChoiceKey]);

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

    return () =>
      window.removeEventListener('hashRouteChange', handleHashRouteChange as EventListener);
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
      const pendingSession = loadSession(id, { historyMode: 'push' });
      setRoutePath(normalizeAppPath(window.location.pathname));
      void pendingSession.then((data) => {
        if (data) {
          setActiveMind(data.mind || null);
          setRoutePath(normalizeAppPath(window.location.pathname));
        }
      });
      setMobileRailOpen(false);
    },
    [currentSessionId, loadSession, markSessionActivitySeen]
  );

  const handleNewPersonalChat = useCallback(() => {
    notifyOnDoneRef.current = false;
    setActiveMind(null);
    setModelChoices((choices) => {
      const next = { ...choices };
      delete next[`${selectionOwner}:new`];
      return next;
    });
    clearChat({ historyMode: 'push' });
    setRoutePath('/');
    setMobileRailOpen(false);
  }, [clearChat, selectionOwner]);

  const handleOpenProject = useCallback((id: string) => {
    setMobileRailOpen(false);
    if (projectIdForPath(window.location.pathname) === id) return;
    notifyOnDoneRef.current = false;
    setActiveMind(null);
    setInitialPrompt(null);
    clearChat({ historyMode: 'none' });
    navigateTo(projectPath(id));
  }, [clearChat, navigateTo]);

  const handleProjectSettings = useCallback((id: string) => {
    setMobileRailOpen(false);
    setProjectDetailsId(id);
  }, []);

  const handleNewChat = useCallback(() => {
    if (activeProject && !isTemporaryChat && !isReadOnly) handleOpenProject(activeProject.id);
    else handleNewPersonalChat();
  }, [activeProject, handleNewPersonalChat, handleOpenProject, isReadOnly, isTemporaryChat]);

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

  const handleAutomationsClick = useCallback(() => {
    clearChat({ historyMode: 'none' });
    navigateTo('/automations');
    setMobileRailOpen(false);
  }, [clearChat, navigateTo]);

  const handlePluginsClick = useCallback(() => {
    clearChat({ historyMode: 'none' });
    navigateTo('/plugins');
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

  const handleEditMind = useCallback(
    (mind: Mind) => {
      clearChat({ historyMode: 'none' });
      navigateTo(`/minds/editor/${encodeURIComponent(mind.public_id)}`);
      setMobileRailOpen(false);
    },
    [clearChat, navigateTo]
  );

  const handleStartMind = useCallback(
    (mind: Mind) => {
      setActiveMind(mind);
      clearChat({ historyMode: 'none' });
      navigateTo(`/?mind=${encodeURIComponent(mind.public_id)}`);
      setMobileRailOpen(false);
    },
    [clearChat, navigateTo]
  );

  const handleMindSaved = useCallback(
    (mind: Mind) => {
      void refreshPinnedMinds();
      navigateTo('/minds');
      setActiveMind((current) => {
        if (current?.public_id === mind.public_id) {
          return mind;
        }
        return current;
      });
    },
    [navigateTo, refreshPinnedMinds]
  );

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
  const isAutomationRoute = routePath === '/automations';
  const isPluginsRoute = routePath === '/plugins';
  const isEditorRoute = routePath === '/minds/editor' || routePath.startsWith('/minds/editor/');
  const isAdminRoute = routePath === '/admin' || routePath.startsWith('/admin/');
  const isChatSurface = !isMindsRoute && !isEditorRoute && !isAdminRoute && !isAutomationRoute && !isPluginsRoute;
  const referenceScope = `${user?.id || ''}:${routePath}:${activeProjectId || ''}`;
  const allowChatReferences = isAuthenticated && isChatSurface && !isTemporaryChat && !isReadOnly &&
    !sessionAccess?.isPublic && (!activeMind || activeMind.is_owner) && !isImageToolModel({ id: selectedModel });
  const chatReferences = allowChatReferences && referenceDraft.scope === referenceScope ? referenceDraft.choices : [];
  const changeChatReferences = (choices: ChatReference[]) => setReferenceDraft({ scope: referenceScope, choices });

  function attachChatReference(choice: ChatReference) {
    if (!allowChatReferences || chatReferences.length >= maxChatReferences ||
      chatReferences.some((item) => item.session_id === choice.session_id)) return;
    changeChatReferences([...chatReferences, choice]);
    setMobileRailOpen(false);
  }
  const showTemporaryChatButton = routePath === '/' && history.length === 0 && !isTemporaryChat;
  const canvasTextdocVersion = canvasTextdoc
    ? `${canvasTextdoc.id || ''}:${canvasTextdoc.updated_at || 0}`
    : '';

  useEffect(() => {
    if (
      !isAuthOpen ||
      isAuthenticated ||
      isTemporaryChat ||
      !currentSessionId ||
      history.length === 0 ||
      !(routePath === '/' || routePath.startsWith('/c/'))
    ) {
      return;
    }

    const transferableHistory = prepareGuestChatTransferHistory(buildHistoryForAPI(null, history));
    if (transferableHistory.length === 0) return;
    stageGuestChatTransfer({
      sessionId: currentSessionId,
      history: transferableHistory,
      mindId: activeMind?.public_id || null,
    });
  }, [
    activeMind?.public_id,
    buildHistoryForAPI,
    currentSessionId,
    history,
    isAuthOpen,
    isAuthenticated,
    isTemporaryChat,
    routePath,
  ]);

  useEffect(() => {
    if (isAuthLoading || !isAuthenticated || guestChatImportStartedRef.current) return;
    const transfer = readGuestChatTransfer();
    if (!transfer) return;

    guestChatImportStartedRef.current = true;
    void apiService
      .importActiveGuestChat(transfer)
      .then(async (data) => {
        clearGuestChatTransfer();
        const sessionId = data.session_id || transfer.sessionId;
        const loaded = await loadSession(sessionId, { historyMode: 'replace' });
        setActiveMind(loaded?.mind || data.mind || null);
        await refreshSessions();
      })
      .catch((error) => {
        guestChatImportStartedRef.current = false;
        console.warn('Failed to import active guest chat', error);
      });
  }, [isAuthLoading, isAuthenticated, loadSession, refreshSessions]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      if (!canvasTextdoc) {
        setCanvasVisible(false);
        setCanvasPreviewVisible(false);
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
  const isCanvasHtmlPreviewActive = Boolean(
    isCanvasPreviewVisible && isCanvasVisible && canvasDockTextdoc?.type === 'code/html'
  );

  const handleOpenCanvas = useCallback((textdoc: CanvasTextdoc) => {
    setSelectedCanvasTextdoc(textdoc);
    if (textdoc.type !== 'code/html') {
      setCanvasPreviewVisible(false);
    }
    setCanvasVisible(true);
  }, []);

  const handleCanvasPreviewToggle = useCallback(() => {
    if (canvasDockTextdoc?.type !== 'code/html') return;
    setCanvasPreviewVisible((current) => !current);
  }, [canvasDockTextdoc?.type]);

  const handleCloseCanvas = useCallback(() => {
    setCanvasPreviewVisible(false);
    setCanvasVisible(false);
  }, []);

  const handleCanvasContentChange = useCallback(
    (content: string) => {
      const targetId = activeCanvasTextdoc?.id || null;
      const updatedAt = Math.floor(Date.now() / 1000);
      const updatedTextdoc = activeCanvasTextdoc
        ? { ...activeCanvasTextdoc, content, updated_at: updatedAt }
        : null;
      setSelectedCanvasTextdoc((current) =>
        current ? { ...current, content, updated_at: updatedAt } : current
      );
      updateCanvasTextdocContent(content, targetId);

      if (!updatedTextdoc || !currentSessionId || isTemporaryChat || isReadOnly) return;
      if (canvasSaveTimerRef.current !== null) {
        window.clearTimeout(canvasSaveTimerRef.current);
      }
      const sessionId = currentSessionId;
      canvasSaveTimerRef.current = window.setTimeout(() => {
        canvasSaveTimerRef.current = null;
        void apiService.saveCanvasTextdoc(sessionId, updatedTextdoc).catch((error) => {
          console.warn('Canvas autosave failed:', error);
        });
      }, 700);
    },
    [activeCanvasTextdoc, currentSessionId, isReadOnly, isTemporaryChat, updateCanvasTextdocContent]
  );

  useEffect(
    () => () => {
      if (canvasSaveTimerRef.current !== null) {
        window.clearTimeout(canvasSaveTimerRef.current);
      }
    },
    []
  );

  const handleCanvasDraftChange = useCallback((content: string) => {
    canvasPreviewRef.current?.render(content);
  }, []);

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
    document.documentElement.classList.toggle(
      'canvas-open',
      shouldShowCanvasDock && isCanvasVisible
    );
    document.documentElement.classList.toggle('canvas-preview-open', isCanvasHtmlPreviewActive);
    document.documentElement.classList.toggle('canvas-resizing', isCanvasResizing);
    document.body.classList.toggle('has-canvas-dock', shouldShowCanvasDock);
    document.body.classList.toggle('canvas-open', shouldShowCanvasDock && isCanvasVisible);
    document.body.classList.toggle('canvas-preview-open', isCanvasHtmlPreviewActive);
    document.body.classList.toggle('canvas-resizing', isCanvasResizing);
    if (shouldShowCanvasDock) {
      document.body.style.setProperty('--canvas-panel-width', `${canvasWidth}px`);
    } else {
      document.body.style.removeProperty('--canvas-panel-width');
    }
    return () => {
      document.documentElement.classList.remove('has-canvas-dock');
      document.documentElement.classList.remove('canvas-open');
      document.documentElement.classList.remove('canvas-preview-open');
      document.documentElement.classList.remove('canvas-resizing');
      document.body.classList.remove('has-canvas-dock');
      document.body.classList.remove('canvas-open');
      document.body.classList.remove('canvas-preview-open');
      document.body.classList.remove('canvas-resizing');
      document.body.style.removeProperty('--canvas-panel-width');
    };
  }, [
    canvasDockTextdoc,
    canvasWidth,
    isCanvasHtmlPreviewActive,
    isCanvasResizing,
    isCanvasVisible,
    isChatSurface,
  ]);

  const canvasDockIsCode = canvasDockTextdoc?.type?.startsWith('code/') ?? false;
  const canvasDockLanguage = canvasDockIsCode ? canvasDockTextdoc?.type.slice('code/'.length) : '';
  const canvasDockTypeLabel = canvasDockTextdoc
    ? canvasDockIsCode
      ? t('canvas.type.code', { language: canvasDockLanguage })
      : t('canvas.type.document')
    : '';
  const canvasDockLineCount = canvasDockTextdoc
    ? (canvasDockTextdoc.content || '').split(/\r\n|\r|\n/).length
    : 0;

  return (
    <>
      <SEOHelmet title={projectRouteId ? t('projects.title') : null} />

      {isAuthenticated && (
        <Suspense fallback={null}>
          <AppRail
            isExpanded={isRailExpanded}
            isMobile={isMobileViewport}
            onToggle={handleRailToggle}
            sessions={visibleSessions}
            sessionActivity={sessionActivity}
            currentSessionId={currentSessionId}
            onSelectSession={handleSelectSession}
            onNewChat={handleNewChat}
            onNewPersonalChat={handleNewPersonalChat}
            onReferenceChat={allowChatReferences && chatReferences.length < maxChatReferences ? attachChatReference : undefined}
            activeProjectId={activeProjectId}
            onOpenProject={handleOpenProject}
            onProjectSettings={handleProjectSettings}
            projectStore={projectStore}
            onSessionMoved={onSessionMoved}
            onProjectsChanged={refreshSessions}
            onMindsClick={handleMindsClick}
            onAutomationsClick={handleAutomationsClick}
            onPluginsClick={handlePluginsClick}
            onAdminClick={handleAdminClick}
            onSettingsClick={() => {
              setMobileRailOpen(false);
              setSettingsOpen(true);
            }}
            currentPath={routePath}
            activeMindId={activeMind?.public_id || null}
            pinnedMinds={pinnedMinds}
            petState={petState}
            onSelectMind={handleStartMind}
            onSessionDeleted={(sessionId) => {
              removeSession(sessionId);
              if (sessionId === currentSessionId) {
                clearChat({ historyMode: 'replace' });
              }
              refreshSessions();
            }}
            onSessionRenamed={onSessionRenamed}
            onCompactSession={(sessionId: string) => compactSession(
              sessionId, sessionId === currentSessionId ? selectedModel : undefined
            )}
            onViewContext={(sessionId: string) => {
              setMobileRailOpen(false);
              setContextSessionId(sessionId);
            }}
          />
        </Suspense>
      )}

      <div
        className={`ui-app-canvas-stage${isCanvasVisible ? ' is-canvas-open' : ''}`}
        style={{ '--canvas-visible-width': `${canvasWidth}px` } as CSSProperties}
      >
        <main
          className={`ui-app-main-shell${isChatSurface && history.length === 0 ? ' is-empty-conversation' : ''}${isCanvasHtmlPreviewActive ? ' canvas-site-preview-mode' : ''}`}
        >
          {isCanvasHtmlPreviewActive && canvasDockTextdoc ? (
            <Suspense fallback={null}>
              <CanvasHtmlPreview ref={canvasPreviewRef} html={canvasDockTextdoc.content || ''} />
            </Suspense>
          ) : (
            <>
              <GlobalHeader
                isAuthenticated={isAuthenticated}
                onMenuToggle={handleRailToggle}
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
                {...(activeProject && !isTemporaryChat && !projectRouteId ? { activeProject } : {})}
              />

              {isAdminRoute ? (
                <Suspense fallback={null}>
                  <AdminPanel
                    isAuthenticated={isAuthenticated}
                    onOpenAuth={() => setAuthOpen('login')}
                  />
                </Suspense>
              ) : isPluginsRoute ? (
                <Suspense fallback={null}>
                  <PluginsPage onOpenAuth={() => setAuthOpen('login')} />
                </Suspense>
              ) : isAutomationRoute ? (
                <Suspense fallback={null}>
                  <AutomationPage
                    models={availableModels}
                    selectedModel={selectedModel}
                    sessions={visibleSessions}
                    onOpenAuth={() => setAuthOpen('login')}
                    onOpenChat={(id) => {
                      void refreshSessions();
                      handleSelectSession(id);
                    }}
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
              ) : projectRouteId && !routedProject ? (
                <div className="ui-empty-conversation-shell">
                  <LandingHero title={t('projects.title')}>
                    {isAuthLoading || (isAuthenticated && !projectStore.loaded && !projectStore.loadError) ? (
                      <p role="status">{t('common.loading')}</p>
                    ) : !isAuthenticated ? (
                      <button type="button" className="project-home-settings" onClick={() => setAuthOpen('login')}>
                        {t('auth.login')}
                      </button>
                    ) : (
                      <p role="status">{t(projectStore.loadError ? 'projects.failed' : 'projects.unavailable')}</p>
                    )}
                  </LandingHero>
                </div>
              ) : projectRouteId || history.length === 0 ? (
                <div className="ui-empty-conversation-shell">
                  <LandingHero isReadOnly={isReadOnly} title={routedProject?.name || null}>
                    {routedProject && (
                      <button type="button" className="project-home-settings" onClick={() => handleProjectSettings(routedProject.id)}>
                        <Settings2 size={16} aria-hidden="true" />
                        {t('projects.details')}
                      </button>
                    )}
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
                                  <BadgeCheck
                                    size={15}
                                    className="ml-1 inline-block align-[-2px]"
                                  />
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
                      key={routedProject?.id || 'landing'}
                      variant="landing"
                      showDynamicWarning={false}
                      onSendMessage={handleSendMessage}
                      onStop={() => {
                        notifyOnDoneRef.current = false;
                        stopGeneration();
                      }}
                      isLoading={isLoading}
                      petState={petState}
                      connectionState={connectionState}
                      queuedMessageCount={queuedMessageCount}
                      isReadOnly={isReadOnly}
                      initialPrompt={initialPrompt}
                      onInitialPromptConsumed={() => setInitialPrompt(null)}
                      onOpenAuth={() => setAuthOpen('login')}
                      currentSessionId={currentSessionId}
                      projectDraftId={routedProject?.id || null}
                      referenceProjectId={routedProject?.id || null}
                      allowChatReferences={allowChatReferences}
                      chatReferences={chatReferences}
                      onChatReferencesChange={changeChatReferences}
                      currentModel={selectedModel}
                      modelUnavailable={modelUnavailable}
                      contextUsage={currentContextUsage}
                      models={availableModels}
                      availableTools={mindTools}
                      onModelChange={chooseModel}
                      serviceTier={selectedSpeed}
                      onServiceTierChange={chooseSpeed}
                      thinkingLevel={selectedThinkingLevel ?? null}
                      onThinkingLevelChange={chooseEffort}
                    />
                    {routedProject && (
                      <ProjectRecentChats
                        sessions={visibleSessions.filter((item) => item.workspace_id === routedProject.id).slice(0, 4)}
                        onOpen={handleSelectSession}
                      />
                    )}
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
                            {activeMind.description && <p>{activeMind.description}</p>}
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
                      petState={petState}
                      currentSessionId={isTemporaryChat ? null : currentSessionId}
                      isReadOnly={isReadOnly}
                      projectId={isAuthenticated && !isTemporaryChat && !isReadOnly && !sessionAccess?.isPublic
                        ? activeProject?.id || '' : ''}
                      onRegenerate={(messageId) => {
                        if (regenerateMessage) {
                          notifyOnDoneRef.current = true;
                          regenerateMessage(
                            messageId,
                            modelForMessage(messageId),
                            selectedThinkingLevel,
                            selectedSpeed
                          );
                        }
                      }}
                      onEdit={(messageId, newText) => {
                        if (editMessage) {
                          notifyOnDoneRef.current = true;
                          editMessage(
                            messageId,
                            newText,
                            modelForMessage(messageId, true),
                            selectedThinkingLevel,
                            selectedSpeed
                          );
                        }
                      }}
                      onSwitchVariant={(messageId, direction) => {
                        if (switchVariant) {
                          switchVariant(messageId, direction);
                        }
                      }}
                      onBeatboxStateChange={updateBeatboxState}
                      onSendMessage={handleSendMessage}
                    />

                    <InputArea
                      onSendMessage={handleSendMessage}
                      onStop={() => {
                        notifyOnDoneRef.current = false;
                        stopGeneration();
                      }}
                      isLoading={isLoading}
                      petState={petState}
                      connectionState={connectionState}
                      queuedMessageCount={queuedMessageCount}
                      isReadOnly={isReadOnly}
                      initialPrompt={initialPrompt}
                      onInitialPromptConsumed={() => setInitialPrompt(null)}
                      onOpenAuth={() => setAuthOpen('login')}
                      currentSessionId={currentSessionId}
                      referenceProjectId={activeProject?.id || null}
                      allowChatReferences={allowChatReferences}
                      chatReferences={chatReferences}
                      onChatReferencesChange={changeChatReferences}
                      currentModel={selectedModel}
                      modelUnavailable={modelUnavailable}
                      contextUsage={currentContextUsage}
                      models={availableModels}
                      availableTools={mindTools}
                      onModelChange={chooseModel}
                      serviceTier={selectedSpeed}
                      onServiceTierChange={chooseSpeed}
                      thinkingLevel={selectedThinkingLevel ?? null}
                      onThinkingLevelChange={chooseEffort}
                    />
                  </>
                </Suspense>
              )}
            </>
          )}
        </main>

        {isChatSurface && canvasDockTextdoc && (
          <aside
            className={
              isCanvasVisible ? 'chat-canvas-dock is-open' : 'chat-canvas-dock is-collapsed'
            }
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
                    key={`${canvasDockTextdoc.id || ''}:${canvasDockTextdoc.name}:${canvasDockTextdoc.type}`}
                    textdoc={canvasDockTextdoc}
                    onClose={handleCloseCanvas}
                    onContentChange={handleCanvasContentChange}
                    onDraftChange={handleCanvasDraftChange}
                    onRepairPython={handleRepairPython}
                    isStreaming={isCanvasStreaming}
                    isPreviewActive={isCanvasHtmlPreviewActive}
                    onPreviewToggle={handleCanvasPreviewToggle}
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
                  {isCanvasStreaming ? (
                    <Pet state={canvasDockIsCode ? 'coding' : 'working'} />
                  ) : canvasDockIsCode ? (
                    <FileCode2 size={18} />
                  ) : (
                    <FileText size={18} />
                  )}
                </span>
                <span className="chat-canvas-dock-copy">
                  <strong>{canvasDockTextdoc.name}</strong>
                  <small>
                    {canvasDockTypeLabel} / {t('canvas.lines', { count: canvasDockLineCount })}
                  </small>
                </span>
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
            onOpenAuth={(mode = 'login') => {
              setSettingsOpen(false);
              setAuthOpen(mode);
              clearHash();
            }}
            onOpenPlugins={() => {
              setSettingsOpen(false);
              clearHash();
              handlePluginsClick();
            }}
            onOpenAutomations={() => {
              setSettingsOpen(false);
              clearHash();
              handleAutomationsClick();
            }}
          />
        </Suspense>
      )}
      {isAuthenticated && contextSessionId && (
        <Suspense fallback={null}>
          <ContextCheckpointModal
            key={String(user?.id) + ':' + contextSessionId}
            sessionId={contextSessionId}
            models={availableModels}
            onClose={() => setContextSessionId(null)}
          />
        </Suspense>
      )}
      {isAuthenticated && projectDetails && (
        <Suspense fallback={null}>
          <ProjectDetailsModal key={projectDetails.id} project={projectDetails} onClose={() => setProjectDetailsId(null)} />
        </Suspense>
      )}

      {(isAuthOpen === 'login' || isAuthOpen === 'register' || isAuthOpen === 'link') && (
        <Suspense fallback={null}>
          <AuthModal
            onClose={() => setAuthOpen(false)}
            initialView={isAuthOpen === 'register' ? 'register' : 'login'}
            authMode={isAuthOpen}
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
            onClose={() =>
              setImageLightbox({
                isOpen: false,
                imageSrc: null,
                messageId: null,
                canRegenerate: true,
                downloadName: null,
              })
            }
            currentModel={
              history
                .find((message) => message.id === imageLightbox.messageId)
                ?.selectedTools?.includes('demo_image')
                ? 'demo_image'
                : modelForMessage(imageLightbox.messageId)
            }
            sessionId={currentSessionId}
            canRegenerate={imageLightbox.canRegenerate}
            downloadName={imageLightbox.downloadName}
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
