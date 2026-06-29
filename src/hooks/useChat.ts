import { useState, useRef, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { apiService, type CanvasTextdoc, type CanvasUpdate } from '../services/api';
import { ALLOW_GUEST_CHATS_SAVE } from '../utils/constants';
import { useSettings } from '../context/SettingsContext';

const DEFAULT_SESSION_ACCESS = {
    isPublic: false,
    isOwner: false,
    publicId: null,
    shareUrl: null,
    readOnly: false
};

const SLUG_INDEX_KEY = 'session_slug_index';
const SESSION_ID_KEY = 'session_id';
const SESSION_SLUG_KEY = 'session_slug';
const GUEST_SESSIONS_KEY = 'guest_chat_history_ids';
const GUEST_SESSION_TOKENS_KEY = 'guest_chat_tokens';

type HistoryMode = 'replace' | 'push' | 'none';

type SyncSessionOptions = {
    previousSessionId?: string | null;
    historyMode?: HistoryMode;
    persistToGuestHistory?: boolean;
    activate?: boolean;
};

type LoadSessionOptions = {
    historyMode?: HistoryMode;
    clearHistory?: boolean;
};

type ClearChatOptions = {
    historyMode?: HistoryMode;
    temporary?: boolean;
};

type SendMessageOptions = {
    webSearch?: boolean;
    autoWebSearch?: boolean;
    censorship?: boolean;
    mindId?: string | null;
    temporaryChat?: boolean;
    [key: string]: unknown;
};

type SessionActivityStatus = 'generating' | 'complete' | 'error';

type SessionActivity = {
    status: SessionActivityStatus;
    updatedAt: number;
    message?: string;
};

const WEB_SEARCH_STATUS_MESSAGE_KEYS = {
    web_search_pending: 'webSearch.status.pending',
    web_search_querying: 'webSearch.status.querying',
    web_search_deciding: 'webSearch.status.deciding',
    web_search_started: 'webSearch.status.started',
    web_search_fetching: 'webSearch.status.fetching',
    web_search_skipped: 'webSearch.status.skipped',
    web_search_done: 'webSearch.status.done',
    web_search_no_results: 'webSearch.status.noResults',
    web_search_failed: 'webSearch.status.failed',
    generating_text: 'webSearch.status.generating'
};

const WEB_SEARCH_STATUS_FALLBACKS = {
    web_search_pending: 'Connecting search...',
    web_search_querying: 'Preparing search query...',
    web_search_deciding: 'Deciding whether search is needed...',
    web_search_started: 'Searching the web...',
    web_search_fetching: 'Opening and reading sources...',
    web_search_skipped: 'Search is not needed, answering without it.',
    web_search_done: 'Sources found.',
    web_search_no_results: 'No suitable sources found.',
    web_search_failed: 'Search failed, answering without sources.',
    generating_text: 'Preparing answer...'
};

function isWebSearchStreamStatus(status) {
    return typeof status === 'string' && (
        status.startsWith('web_search_') ||
        status === 'generating_text'
    );
}

function getWebSearchStatus(data, t) {
    const status = typeof data?.status === 'string' ? data.status : 'web_search_pending';
    const key = WEB_SEARCH_STATUS_MESSAGE_KEYS[status];
    const fallback = WEB_SEARCH_STATUS_FALLBACKS[status] || WEB_SEARCH_STATUS_FALLBACKS.web_search_pending;
    return {
        status,
        message: key
            ? t(key, { defaultValue: fallback })
            : (typeof data?.message === 'string' && data.message.trim() ? data.message.trim() : fallback),
        query: typeof data?.query === 'string' ? data.query : undefined
    };
}

function createDefaultSessionAccess() {
    return { ...DEFAULT_SESSION_ACCESS };
}

function generateSessionId() {
    return crypto.randomUUID();
}

function generateTemporarySessionId() {
    return `temp_${crypto.randomUUID()}`;
}

function slugify(text) {
    return (text || '').toString()
        .normalize('NFKD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .replace(/[^a-z0-9\u0400-\u04FF\s-]/g, '')
        .trim()
        .replace(/[\s_-]+/g, '-')
        .replace(/^-+|-+$/g, '');
}

function normalizeHistoryMessage(msg) {
    const parts = msg.parts || [];
    let text = parts.find((part) => part.text)?.text || '';

    if (text.trim().startsWith('{') && text.trim().endsWith('}')) {
        try {
            const parsed = JSON.parse(text);
            if (parsed.url_path || parsed.original_name || parsed.mime_type) {
                text = '';
            }
        } catch {
        }
    }

    text = text.replace(/---\s*File:\s*[^-\n]+---[\s\S]*?---\s*End\s*File\s*---/gi, '');
    text = text.replace(/\[Binary\s+file:[^\]]+\]/gi, '');

    const images = parts.filter((part) => part.image).map((part) => part.image.url_path || part.image) || [];
    const files = parts.filter((part) => part.file).map((part) => ({
        file: {
            url_path: part.file.url_path || part.file,
            original_name: part.file.original_name || part.file.name || 'file',
            mime_type: part.file.mime_type || 'application/octet-stream',
            size: part.file.size || 0
        }
    })) || [];

    return {
        id: msg.id || Math.random().toString(36).substr(2, 9),
        role: msg.role,
        content: text.trim(),
        images,
        files,
        sources: Array.isArray(msg.sources) ? msg.sources : [],
        githubTool: msg.github_tool || msg.githubTool || null,
        canvasTextdoc: normalizeCanvasTextdoc(msg.canvas_textdoc || msg.canvasTextdoc),
        canvasUpdates: Array.isArray(msg.canvas_updates || msg.canvasUpdates)
            ? (msg.canvas_updates || msg.canvasUpdates)
            : [],
        timestamp: msg.timestamp,
        parts
    };
}

function normalizeCanvasTextdoc(value): CanvasTextdoc | null {
    if (!value || typeof value !== 'object') {
        return null;
    }

    const name = typeof value.name === 'string' ? value.name : '';
    const type = typeof value.type === 'string' ? value.type : '';
    if (!name || !type) {
        return null;
    }

    return {
        id: typeof value.id === 'string' ? value.id : undefined,
        name,
        type,
        content: typeof value.content === 'string' ? value.content : '',
        comments: Array.isArray(value.comments) ? value.comments : [],
        updated_at: typeof value.updated_at === 'number' ? value.updated_at : undefined
    };
}

function extractLatestCanvasTextdoc(messages): CanvasTextdoc | null {
    if (!Array.isArray(messages)) {
        return null;
    }

    for (let index = messages.length - 1; index >= 0; index -= 1) {
        const textdoc = normalizeCanvasTextdoc(messages[index]?.canvasTextdoc || messages[index]?.canvas_textdoc);
        if (textdoc) {
            return textdoc;
        }
    }

    return null;
}

function normalizeBeatboxState(value) {
    if (!value || typeof value !== 'object') {
        return null;
    }

    const rawMeta = value.meta && typeof value.meta === 'object' ? value.meta : {};
    const bpm = Math.max(40, Math.min(240, Number.parseInt(rawMeta.bpm, 10) || 120));
    const bars = Math.max(1, Math.min(16, Number.parseInt(rawMeta.bars, 10) || 1));
    const rawTracks = Array.isArray(value.tracks) ? value.tracks : [];
    const tracks = rawTracks.slice(0, 32).map((track, index) => {
        if (!track || typeof track !== 'object') {
            return null;
        }
        const steps = Array.isArray(track.steps)
            ? track.steps.slice(0, bars * 16).map(step => step === 1 || step === true ? 1 : 0)
            : [];
        if (!steps.length) {
            return null;
        }
        const adsr = track.adsr && typeof track.adsr === 'object' ? track.adsr : {};
        return {
            id: typeof track.id === 'string' && track.id.trim() ? track.id.slice(0, 80) : `track_${index + 1}`,
            type: 'drum',
            drum: typeof track.drum === 'string' && track.drum.trim() ? track.drum.slice(0, 40) : 'kick',
            steps,
            adsr: {
                attack: Number.isFinite(Number(adsr.attack)) ? Number(adsr.attack) : 0.001,
                decay: Number.isFinite(Number(adsr.decay)) ? Number(adsr.decay) : 0.1,
                sustain: Number.isFinite(Number(adsr.sustain)) ? Number(adsr.sustain) : 0,
                release: Number.isFinite(Number(adsr.release)) ? Number(adsr.release) : 0.05
            }
        };
    }).filter(Boolean);

    if (!tracks.length) {
        return null;
    }

    return {
        meta: { bpm, bars },
        tracks,
        isPlaying: false,
        currentStep: 0,
        timerId: null
    };
}

function extractLatestBeatboxState(messages) {
    if (!Array.isArray(messages)) {
        return null;
    }

    for (let index = messages.length - 1; index >= 0; index -= 1) {
        const texts = [];
        if (typeof messages[index]?.content === 'string') {
            texts.push(messages[index].content);
        }
        if (Array.isArray(messages[index]?.parts)) {
            messages[index].parts.forEach((part) => {
                if (typeof part?.text === 'string') {
                    texts.push(part.text);
                }
            });
        }
        for (const text of texts) {
            const matches = [...text.matchAll(/<beatbox>([\s\S]*?)<\/beatbox>/gi)];
            for (let matchIndex = matches.length - 1; matchIndex >= 0; matchIndex -= 1) {
                try {
                    const state = normalizeBeatboxState(JSON.parse(matches[matchIndex][1].trim()));
                    if (state) {
                        return state;
                    }
                } catch {
                }
            }
        }

        const widgets = messages[index]?.widgets;
        if (!Array.isArray(widgets)) {
            continue;
        }
        for (let widgetIndex = widgets.length - 1; widgetIndex >= 0; widgetIndex -= 1) {
            const widget = widgets[widgetIndex];
            if (widget?.type === 'beatbox') {
                const state = normalizeBeatboxState(widget.state);
                if (state) {
                    return state;
                }
            }
        }
    }

    return null;
}

export const useChat = () => {
    const { t } = useTranslation();
    const { settings } = useSettings();
    const [history, setHistory] = useState([]);
    const [canvasTextdoc, setCanvasTextdoc] = useState<CanvasTextdoc | null>(null);
    const [beatboxState, setBeatboxState] = useState(null);
    const [isLoading, setIsLoading] = useState(false);
    const [currentSessionId, setCurrentSessionId] = useState(null);
    const [currentSessionSlug, setCurrentSessionSlug] = useState(null);
    const [sessionAccess, setSessionAccess] = useState(createDefaultSessionAccess);
    const [isReadOnly, setIsReadOnly] = useState(false);
    const [isTemporaryChat, setIsTemporaryChat] = useState(false);
    const [sessionActivity, setSessionActivity] = useState<Record<string, SessionActivity>>({});
    const [optimisticSessions, setOptimisticSessions] = useState({});
    const sessionActivityRef = useRef<Record<string, SessionActivity>>({});
    const sessionHistoryCacheRef = useRef(new Map());
    const sessionAbortControllersRef = useRef(new Map());
    const sessionRequestIdsRef = useRef(new Map());
    const nextChatRequestIdRef = useRef(0);
    const messageVariantsRef = useRef(new Map());
    const slugIndexCacheRef = useRef({});
    const sessionLoadRequestIdRef = useRef(0);
    const currentSessionIdRef = useRef(null);
    const currentSessionSlugRef = useRef(null);
    const canvasTextdocRef = useRef<CanvasTextdoc | null>(null);
    const beatboxStateRef = useRef(null);
    const activeMindIdRef = useRef(null);
    const temporaryChatRef = useRef(false);

    const setCanvasTextdocState = useCallback((value) => {
        const normalized = normalizeCanvasTextdoc(value);
        canvasTextdocRef.current = normalized;
        setCanvasTextdoc(normalized);
    }, []);

    const applyCanvasUpdate = useCallback((update: CanvasUpdate | null | undefined) => {
        if (!update || typeof update !== 'object') {
            return;
        }
        if ('textdoc' in update) {
            setCanvasTextdocState(update.textdoc);
        }
    }, [setCanvasTextdocState]);

    const updateBeatboxState = useCallback((value) => {
        const normalized = normalizeBeatboxState(value);
        beatboxStateRef.current = normalized;
        setBeatboxState(normalized);
    }, []);

    const updateCanvasTextdocContent = useCallback((content: string, textdocId?: string | null) => {
        const current = canvasTextdocRef.current;
        if (!current) {
            return;
        }

        const shouldUpdateGlobal = !textdocId || !current.id || current.id === textdocId;
        const updatedTextdoc = {
            ...current,
            content,
            updated_at: Math.floor(Date.now() / 1000)
        };

        if (shouldUpdateGlobal) {
            canvasTextdocRef.current = updatedTextdoc;
            setCanvasTextdoc(updatedTextdoc);
        }

        const targetId = textdocId || current.id || null;
        setHistory(prev => prev.map((message) => {
            const messageTextdoc = normalizeCanvasTextdoc(message.canvasTextdoc || message.canvas_textdoc);
            const isTarget = messageTextdoc && (
                (targetId && messageTextdoc.id === targetId) ||
                (!targetId && messageTextdoc.name === current.name && messageTextdoc.type === current.type)
            );

            if (!isTarget) {
                return message;
            }

            const nextTextdoc = {
                ...messageTextdoc,
                content,
                updated_at: updatedTextdoc.updated_at
            };

            return {
                ...message,
                canvasTextdoc: nextTextdoc,
                variants: Array.isArray(message.variants)
                    ? message.variants.map((variant) => {
                        const variantTextdoc = normalizeCanvasTextdoc(variant.canvasTextdoc || variant.canvas_textdoc);
                        const variantIsTarget = variantTextdoc && (
                            (targetId && variantTextdoc.id === targetId) ||
                            (!targetId && variantTextdoc.name === current.name && variantTextdoc.type === current.type)
                        );
                        return variantIsTarget
                            ? { ...variant, canvasTextdoc: { ...variantTextdoc, content, updated_at: updatedTextdoc.updated_at } }
                            : variant;
                    })
                    : message.variants
            };
        }));
    }, []);

    const setTemporaryChatMode = useCallback((enabled) => {
        temporaryChatRef.current = !!enabled;
        setIsTemporaryChat(!!enabled);
    }, []);

    const updateSessionIdentity = useCallback((sessionId, slug) => {
        currentSessionIdRef.current = sessionId;
        currentSessionSlugRef.current = slug;
        setCurrentSessionId(sessionId);
        setCurrentSessionSlug(slug);
    }, []);

    const setSessionActivityState = useCallback((sessionId, status: SessionActivityStatus | null, message = '') => {
        if (!sessionId) return;

        setSessionActivity((previous) => {
            const next = { ...previous };
            if (status) {
                next[sessionId] = {
                    status,
                    updatedAt: Date.now(),
                    ...(message ? { message } : {})
                };
            } else {
                delete next[sessionId];
            }
            sessionActivityRef.current = next;
            return next;
        });

        if (currentSessionIdRef.current === sessionId) {
            setIsLoading(status === 'generating');
        }
    }, []);

    const markSessionActivitySeen = useCallback((sessionId) => {
        if (!sessionId) return;
        const currentActivity = sessionActivityRef.current[sessionId];
        if (!currentActivity || currentActivity.status === 'generating') {
            return;
        }
        setSessionActivity((previous) => {
            const next = { ...previous };
            delete next[sessionId];
            sessionActivityRef.current = next;
            return next;
        });
    }, []);

    const isSessionRequestCurrent = useCallback((sessionId, requestId) => (
        sessionRequestIdsRef.current.get(sessionId) === requestId
    ), []);

    const updateSessionHistory = useCallback((sessionId, updater) => {
        if (!sessionId) return [];
        const previousHistory = sessionHistoryCacheRef.current.get(sessionId) || [];
        const nextHistory = typeof updater === 'function'
            ? updater(previousHistory)
            : updater;

        sessionHistoryCacheRef.current.set(sessionId, nextHistory);
        if (currentSessionIdRef.current === sessionId) {
            setHistory(nextHistory);
        }
        return nextHistory;
    }, []);

    const beginSessionRequest = useCallback((sessionId) => {
        const previousController = sessionAbortControllersRef.current.get(sessionId);
        if (previousController) {
            previousController.abort();
        }

        const requestId = nextChatRequestIdRef.current + 1;
        nextChatRequestIdRef.current = requestId;
        const controller = new AbortController();

        sessionAbortControllersRef.current.set(sessionId, controller);
        sessionRequestIdsRef.current.set(sessionId, requestId);
        setSessionActivityState(sessionId, 'generating');

        return { requestId, controller };
    }, [setSessionActivityState]);

    const completeSessionRequest = useCallback((sessionId, requestId, status: SessionActivityStatus | null = 'complete', message = '') => {
        if (!isSessionRequestCurrent(sessionId, requestId)) {
            return false;
        }

        sessionAbortControllersRef.current.delete(sessionId);
        sessionRequestIdsRef.current.delete(sessionId);

        if (!status || currentSessionIdRef.current === sessionId) {
            setSessionActivityState(sessionId, null);
        } else {
            setSessionActivityState(sessionId, status, message);
        }

        return true;
    }, [isSessionRequestCurrent, setSessionActivityState]);

    const upsertOptimisticSession = useCallback((sessionId, text, files = []) => {
        if (!sessionId) return;
        const filePreview = files.length > 0
            ? files.map((file) => file?.name).filter(Boolean).join(', ')
            : '';
        const preview = (String(text || '').trim() || filePreview || 'New chat').slice(0, 80);

        setOptimisticSessions((previous) => ({
            ...previous,
            [sessionId]: {
                session_id: sessionId,
                title: previous[sessionId]?.title || preview,
                last_message: preview,
                last_updated: Date.now() / 1000
            }
        }));
    }, []);

    const syncBrowserPath = useCallback((path, historyMode = 'replace') => {
        if (historyMode === 'none' || !path) return;

        if (historyMode === 'push') {
            if (window.location.pathname !== path) {
                window.history.pushState({}, '', path);
            }
            return;
        }

        if (window.location.pathname !== path) {
            window.history.replaceState({}, '', path);
        }
    }, []);

    const loadSlugIndex = useCallback(() => {
        try {
            const raw = localStorage.getItem(SLUG_INDEX_KEY);
            slugIndexCacheRef.current = raw ? JSON.parse(raw) : {};
        } catch {
            slugIndexCacheRef.current = {};
        }
    }, []);
    const saveSlugIndex = useCallback(() => {
        try {
            localStorage.setItem(SLUG_INDEX_KEY, JSON.stringify(slugIndexCacheRef.current));
        } catch (e) {
            console.warn('Failed to save slug index', e);
        }
    }, []);
    const registerSessionSlug = useCallback((sessionId, slug) => {
        if (!sessionId || !slug) return;
        slugIndexCacheRef.current[slug] = sessionId;
        saveSlugIndex();
    }, [saveSlugIndex]);
    const sessionIdToSlug = useCallback((sessionId) => slugify(sessionId), []);
    const slugToSessionId = useCallback((slug) => {
        const indexed = slugIndexCacheRef.current[slug];
        if (indexed) return indexed;
        return slug;
    }, []);

    const syncPersistedCurrentSession = useCallback((sessionId, slug) => {
        if (!ALLOW_GUEST_CHATS_SAVE) return;
        try {
            if (sessionId) {
                localStorage.setItem(SESSION_ID_KEY, sessionId);
            } else {
                localStorage.removeItem(SESSION_ID_KEY);
            }

            if (slug) {
                localStorage.setItem(SESSION_SLUG_KEY, slug);
            } else {
                localStorage.removeItem(SESSION_SLUG_KEY);
            }
        } catch (error) {
            console.warn('Failed to persist current session', error);
        }
    }, []);

    const addGuestSession = useCallback((sessionId) => {
        if (!ALLOW_GUEST_CHATS_SAVE || !sessionId) return;
        try {
            const raw = localStorage.getItem(GUEST_SESSIONS_KEY);
            const parsed = raw ? JSON.parse(raw) : [];
            const list = Array.isArray(parsed) ? parsed : [];
            const nextList = [sessionId, ...list.filter((id) => id !== sessionId)].slice(0, 50);
            localStorage.setItem(GUEST_SESSIONS_KEY, JSON.stringify(nextList));
        } catch (e) {
            console.warn('Guest session storage error', e);
        }
    }, []);

    const removeGuestSession = useCallback((sessionId) => {
        if (!ALLOW_GUEST_CHATS_SAVE || !sessionId) return;
        try {
            const raw = localStorage.getItem(GUEST_SESSIONS_KEY);
            const parsed = raw ? JSON.parse(raw) : [];
            const list = Array.isArray(parsed) ? parsed : [];
            localStorage.setItem(GUEST_SESSIONS_KEY, JSON.stringify(list.filter((id) => id !== sessionId)));
        } catch (e) {
            console.warn('Guest session removal error', e);
        }
    }, []);

    const storeGuestSessionToken = useCallback((sessionId, token) => {
        if (!ALLOW_GUEST_CHATS_SAVE || !sessionId || !token) return;
        try {
            const raw = localStorage.getItem(GUEST_SESSION_TOKENS_KEY);
            const tokens = raw ? JSON.parse(raw) : {};
            tokens[sessionId] = token;
            localStorage.setItem(GUEST_SESSION_TOKENS_KEY, JSON.stringify(tokens));
        } catch (e) {
            console.warn('Guest session token storage error', e);
        }
    }, []);

    const removeGuestSessionToken = useCallback((sessionId) => {
        if (!ALLOW_GUEST_CHATS_SAVE || !sessionId) return;
        try {
            const raw = localStorage.getItem(GUEST_SESSION_TOKENS_KEY);
            const tokens = raw ? JSON.parse(raw) : {};
            if (!tokens || typeof tokens !== 'object' || !(sessionId in tokens)) {
                return;
            }
            delete tokens[sessionId];
            localStorage.setItem(GUEST_SESSION_TOKENS_KEY, JSON.stringify(tokens));
        } catch (e) {
            console.warn('Guest session token removal error', e);
        }
    }, []);

    useEffect(() => {
        loadSlugIndex();
    }, [loadSlugIndex]);

    useEffect(() => {
        if (currentSessionId) {
            sessionHistoryCacheRef.current.set(currentSessionId, history);
        }
    }, [currentSessionId, history]);

    const resetConversationState = useCallback(() => {
        setHistory([]);
        setCanvasTextdocState(null);
        updateBeatboxState(null);
        updateSessionIdentity(null, null);
        setSessionAccess(createDefaultSessionAccess());
        setIsReadOnly(false);
        activeMindIdRef.current = null;
        messageVariantsRef.current.clear();
    }, [setCanvasTextdocState, updateBeatboxState, updateSessionIdentity]);

    const syncSessionIdentity = useCallback((sessionId, slug, options: SyncSessionOptions = {}) => {
        if (!sessionId) return;

        const {
            previousSessionId = null,
            historyMode = 'replace',
            persistToGuestHistory = true,
            activate = true
        } = options;

        registerSessionSlug(sessionId, slug);

        if (persistToGuestHistory) {
            addGuestSession(sessionId);
            if (previousSessionId && previousSessionId !== sessionId) {
                removeGuestSession(previousSessionId);
                removeGuestSessionToken(previousSessionId);
            }
        }

        if (activate) {
            updateSessionIdentity(sessionId, slug);
            syncPersistedCurrentSession(sessionId, slug);
            syncBrowserPath(`/c/${encodeURIComponent(slug)}`, historyMode);
        }
    }, [
        addGuestSession,
        registerSessionSlug,
        removeGuestSession,
        removeGuestSessionToken,
        syncBrowserPath,
        syncPersistedCurrentSession,
        updateSessionIdentity
    ]);

    useEffect(() => () => {
        sessionLoadRequestIdRef.current += 1;
        sessionAbortControllersRef.current.forEach((controller) => controller.abort());
        sessionAbortControllersRef.current.clear();
        sessionRequestIdsRef.current.clear();
    }, []);

    const loadSession = useCallback(async (sessionIdOrSlug, options: LoadSessionOptions = {}) => {
        const { historyMode = 'replace', clearHistory = true } = options;
        const loadRequestId = sessionLoadRequestIdRef.current + 1;
        sessionLoadRequestIdRef.current = loadRequestId;
        activeMindIdRef.current = null;
        const requestedSessionId = slugToSessionId(sessionIdOrSlug);
        const cachedHistory = sessionHistoryCacheRef.current.get(requestedSessionId);
        const cachedActivity = sessionActivityRef.current[requestedSessionId];

        if (clearHistory) {
            setHistory(Array.isArray(cachedHistory) ? cachedHistory : []);
            setCanvasTextdocState(extractLatestCanvasTextdoc(cachedHistory));
            updateBeatboxState(extractLatestBeatboxState(cachedHistory));
            setSessionAccess(createDefaultSessionAccess());
            setIsReadOnly(false);
            messageVariantsRef.current.clear();
        }
        setIsLoading(cachedActivity?.status === 'generating');

        if (Array.isArray(cachedHistory) && cachedActivity?.status === 'generating') {
            const slug = sessionIdToSlug(requestedSessionId);
            syncSessionIdentity(requestedSessionId, slug, { historyMode });
            return {
                session_id: requestedSessionId,
                history: cachedHistory,
                mind: null
            };
        }

        try {
            const data = await apiService.getSessionHistory(requestedSessionId);

            if (sessionLoadRequestIdRef.current !== loadRequestId) {
                return;
            }

            if (data && Array.isArray(data.history)) {
                const normalized = data.history.map(normalizeHistoryMessage);
                const resolvedSessionId = data.session_id || requestedSessionId;
                const slug = data.public_id || sessionIdToSlug(resolvedSessionId);
                const accessState = {
                    isPublic: !!data.is_public,
                    isOwner: !!data.is_owner,
                    publicId: data.public_id || null,
                    shareUrl: data.share_url || (data.public_id ? `${window.location.origin}/c/${data.public_id}` : null),
                    readOnly: !!(data.read_only || (data.is_public && !data.is_owner))
                };

                setHistory(normalized);
                setCanvasTextdocState(extractLatestCanvasTextdoc(normalized));
                updateBeatboxState(extractLatestBeatboxState(normalized));
                sessionHistoryCacheRef.current.set(resolvedSessionId, normalized);
                setSessionAccess(accessState);
                setIsReadOnly(accessState.readOnly);
                setTemporaryChatMode(false);
                activeMindIdRef.current = data.mind?.public_id || null;
                syncSessionIdentity(resolvedSessionId, slug, { historyMode });
                setIsLoading(sessionActivityRef.current[resolvedSessionId]?.status === 'generating');
                return data;
            }

            resetConversationState();
            syncPersistedCurrentSession(null, null);
            syncBrowserPath('/', 'replace');
            setIsLoading(false);
            return null;
        } catch (e) {
            if (sessionLoadRequestIdRef.current !== loadRequestId) {
                return;
            }

            console.error('Failed to load session', e);
            resetConversationState();
            syncPersistedCurrentSession(null, null);
            syncBrowserPath('/', 'replace');
            setIsLoading(false);
            return null;
        }
    }, [
        resetConversationState,
        sessionIdToSlug,
        setTemporaryChatMode,
        setCanvasTextdocState,
        slugToSessionId,
        syncBrowserPath,
        syncPersistedCurrentSession,
        syncSessionIdentity
    ]);

    const clearChat = useCallback((options: ClearChatOptions = {}) => {
        const { historyMode = 'push', temporary = false } = options;
        sessionLoadRequestIdRef.current += 1;
        resetConversationState();
        setTemporaryChatMode(temporary);
        syncPersistedCurrentSession(null, null);
        setIsLoading(false);
        syncBrowserPath('/', historyMode);
    }, [resetConversationState, setTemporaryChatMode, syncBrowserPath, syncPersistedCurrentSession]);

    const startTemporaryChat = useCallback((options: ClearChatOptions = {}) => {
        clearChat({ ...options, temporary: true });
    }, [clearChat]);

    const setActiveSessionMindId = useCallback((mindId = null) => {
        activeMindIdRef.current = typeof mindId === 'string' && mindId.trim()
            ? mindId.trim()
            : null;
    }, []);

    const buildHistoryForAPI = useCallback((untilIndex = null) => {
        const historyArray = [];
        const stopIndex = untilIndex !== null ? untilIndex : history.length;

        for (let i = 0; i < stopIndex; i++) {
            const msg = history[i];
            if (!msg || msg.isLoading) continue;

            const isUser = msg.role === 'user';
            const parts = [];

            if (isUser) {
                const content = msg.content || '';
                if (content && content.trim()) {
                    parts.push({ text: content });
                }
                if (msg.files && Array.isArray(msg.files)) {
                    msg.files.forEach(fileInfo => {
                        if (fileInfo?.file) {
                            parts.push({
                                file: {
                                    url_path: fileInfo.file.url_path,
                                    mime_type: fileInfo.file.mime_type,
                                    original_name: fileInfo.file.original_name
                                }
                            });
                        }
                    });
                }
                if (msg.images && Array.isArray(msg.images)) {
                    msg.images.forEach(imgPath => {
                        parts.push({
                            image: {
                                url_path: imgPath
                            }
                        });
                    });
                }
                if (msg.parts && Array.isArray(msg.parts) && msg.parts.length > 0) {
                    const updatedParts = msg.parts.map(p => {
                        if (p.text && content && content.trim()) {
                            return { ...p, text: content };
                        }
                        return p;
                    });
                    if (updatedParts.length > 0) {
                        historyArray.push({
                            role: 'user',
                            parts: updatedParts
                        });
                        continue;
                    }
                }
            } else {
                let content = '';
                if (msg.variants && msg.variants.length > 0) {
                    const currentIndex = msg.currentVariantIndex || 0;
                    const variant = msg.variants[currentIndex];
                    if (variant) {
                        content = variant.content || msg.content || '';
                    } else {
                        content = msg.content || '';
                    }
                } else {
                    content = msg.content || '';
                }

                if (content && content.trim()) {
                    parts.push({ text: content });
                }
                if (msg.variants && msg.variants.length > 0) {
                    const currentIndex = msg.currentVariantIndex || 0;
                    const variant = msg.variants[currentIndex];
                    if (variant && variant.images && Array.isArray(variant.images)) {
                        variant.images.forEach(imgPath => {
                            parts.push({
                                image: {
                                    url_path: imgPath
                                }
                            });
                        });
                    }
                } else if (msg.images && Array.isArray(msg.images)) {
                    msg.images.forEach(imgPath => {
                        parts.push({
                            image: {
                                url_path: imgPath
                            }
                        });
                    });
                }
            }

            if (parts.length > 0) {
                const historyMessage: Record<string, unknown> = {
                    role: isUser ? 'user' : 'model',
                    parts: parts
                };
                const githubTool = msg.githubTool || msg.github_tool;
                if (!isUser && githubTool && typeof githubTool === 'object') {
                    historyMessage.github_tool = githubTool;
                }
                historyArray.push(historyMessage);
            }
        }
        return historyArray;
    }, [history]);
    const sendMessage = useCallback(async (text, files = [], model = 'gemini', options: SendMessageOptions = {}) => {
        const {
            webSearch = false,
            autoWebSearch: requestedAutoWebSearch,
            censorship = false,
            mindId = undefined,
            temporaryChat: requestedTemporaryChat,
            ...metadata
        } = options;
        const autoWebSearch = requestedAutoWebSearch ?? !!settings?.automaticWebSearch;
        const temporaryChat = requestedTemporaryChat ?? temporaryChatRef.current;
        if ((!text || !text.trim()) && files.length === 0) return;
        if (isReadOnly) {
            console.warn('Attempt to send message in read-only chat is blocked.');
            return;
        }

        sessionLoadRequestIdRef.current += 1;
        let sessionId = currentSessionIdRef.current;
        const path = window.location.pathname;
        const isNewChat = path === '/' || !path.startsWith('/c/');

        if (!sessionId || isNewChat) {
            sessionId = temporaryChat ? generateTemporarySessionId() : generateSessionId();
            const slug = sessionIdToSlug(sessionId);
            updateSessionIdentity(sessionId, slug);
            setSessionAccess(createDefaultSessionAccess());
            setIsReadOnly(false);
            setTemporaryChatMode(temporaryChat);

            if (!temporaryChat) {
                registerSessionSlug(sessionId, slug);
                syncPersistedCurrentSession(sessionId, slug);
                addGuestSession(sessionId);
            }

            if (isNewChat && !temporaryChat) {
                syncBrowserPath(`/c/${encodeURIComponent(slug)}`, 'push');
            }
        }
        sessionHistoryCacheRef.current.set(sessionId, history);
        const { requestId: chatRequestId, controller } = beginSessionRequest(sessionId);
        if (!temporaryChat) {
            upsertOptimisticSession(sessionId, text, files);
        }
        const userMsg = {
            id: `user-${Date.now()}`,
            role: 'user',
            content: text,
            files: files.map(f => ({ file: { original_name: f.name } })),
            timestamp: Date.now() / 1000
        };
        const aiMsgId = `ai-${Date.now()}`;
        const aiMsg = {
            id: aiMsgId,
            role: 'model',
            content: '',
            isLoading: true,
            sources: [],
            webSearchStatus: webSearch
                ? getWebSearchStatus({ status: 'web_search_querying' }, t)
                    : null,
            timestamp: Date.now() / 1000
        };

        updateSessionHistory(sessionId, prev => [...prev, userMsg, aiMsg]);

        const formData = new FormData();
        formData.append('message', text);
        formData.append('model', model);
        formData.append('session_id', sessionId);
        formData.append('history', JSON.stringify(buildHistoryForAPI(history.length)));
        if (canvasTextdocRef.current) {
            formData.append('canvas_textdoc', JSON.stringify(canvasTextdocRef.current));
        }
        if (beatboxStateRef.current) {
            formData.append('beatbox_state', JSON.stringify(beatboxStateRef.current));
        }
        formData.append('webSearch', String(webSearch));
        formData.append('autoWebSearch', String(autoWebSearch));
        formData.append('censorship', String(censorship));
        formData.append('temporary_chat', String(temporaryChat));
        if (mindId !== undefined) {
            activeMindIdRef.current = typeof mindId === 'string' && mindId.trim()
                ? mindId.trim()
                : null;
        }
        const effectiveMindId = activeMindIdRef.current;
        if (effectiveMindId) {
            formData.append('mind_id', effectiveMindId);
        }
        files.forEach((file, index) => {
            formData.append(`file${index}`, file, file.name);
        });
        try {
            const screen_dimensions = { width: window.screen.width, height: window.screen.height };
            const page_dimensions = { width: window.innerWidth, height: window.innerHeight };
            const theme = document.documentElement.getAttribute('data-theme') || '';
            const device_pixel_ratio = window.devicePixelRatio || 1;
            const user_agent = navigator.userAgent || '';
            const platform_type = (navigator.userAgentData && navigator.userAgentData.platform) ? navigator.userAgentData.platform : navigator.platform || '';
            const device_type = /Mobi|Android|iPhone|iPad/i.test(user_agent) ? 'mobile' : 'desktop';
            const time_since_visit_seconds = Math.floor((Date.now() - (window.pageLoadTime || Date.now())) / 1000);
            const local_hour = new Date().getHours();
            const avg_conversation_depth = history.length;
            const avg_message_length = history.length > 0
                ? Math.floor(history.reduce((sum, msg) => sum + (msg.content?.length || 0), 0) / history.length)
                : 0;
            const personalizationFields = ['personalization_instructions', 'personalization_nickname', 'personalization_profession', 'personalization_more'];
            const personalizationData = {};
            personalizationFields.forEach(key => {
                try {
                    const value = localStorage.getItem(`settings_${key}`);
                    if (value !== null && value !== '') {
                        personalizationData[key] = JSON.parse(value);
                    }
                } catch {
                }
            });

            const meta = {
                screen_dimensions,
                page_dimensions,
                theme,
                device_pixel_ratio,
                user_agent,
                platform_type,
                device_type,
                time_since_visit_seconds,
                local_hour,
                avg_conversation_depth,
                avg_message_length,
                ...personalizationData,
                ...metadata
            };
            formData.append('meta', JSON.stringify(meta));
        } catch (e) {
            console.warn('Failed to build metadata', e);
        }
        let fullReply = '';
        let firstChunk = true;

        try {
            await apiService.chat(formData, controller.signal, {
                onPart: (data) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId) || !data) return;
                    if (data.status === 'generating_image') {
                        updateSessionHistory(sessionId, prev => prev.map(msg => {
                            if (msg.id === aiMsgId) {
                                return { ...msg, isGeneratingImage: true, imagePrompt: data.prompt };
                            }
                            return msg;
                        }));
                        firstChunk = false;
                        return;
                    }

                    if (isWebSearchStreamStatus(data.status)) {
                        const nextStatus = getWebSearchStatus(data, t);
                        updateSessionHistory(sessionId, prev => prev.map(msg => {
                            if (msg.id !== aiMsgId) {
                                return msg;
                            }
                            if (data.status === 'generating_text' && !msg.webSearchStatus) {
                                return msg;
                            }
                            return {
                                ...msg,
                                isGeneratingImage: false,
                                isLoading: true,
                                webSearchStatus: {
                                    ...nextStatus,
                                    query: nextStatus.query || msg.webSearchStatus?.query
                                },
                                sources: Array.isArray(data.sources) ? data.sources : msg.sources
                            };
                        }));
                        firstChunk = false;
                        return;
                    }

                    if (data.reply_part || data.images) {
                        updateSessionHistory(sessionId, prev => prev.map(msg => {
                            if (msg.id === aiMsgId) {
                                return { ...msg, isGeneratingImage: false, webSearchStatus: null };
                            }
                            return msg;
                        }));
                    }

                    if (firstChunk) {
                        updateSessionHistory(sessionId, prev => prev.map(msg => {
                            if (msg.id === aiMsgId) {
                                return { ...msg, isGeneratingImage: false, webSearchStatus: null };
                            }
                            return msg;
                        }));
                        firstChunk = false;
                    }

                    if (data.images) {
                        updateSessionHistory(sessionId, prev => prev.map(msg => {
                            if (msg.id === aiMsgId) {
                                return { ...msg, images: data.images, isLoading: true };
                            }
                            return msg;
                        }));
                    }

                    if (data.sources) {
                        updateSessionHistory(sessionId, prev => prev.map(msg => {
                            if (msg.id === aiMsgId) {
                                return { ...msg, sources: data.sources, isLoading: true };
                            }
                            return msg;
                        }));
                    }

                    if (data.reply_part) {
                        fullReply += data.reply_part;
                        updateSessionHistory(sessionId, prev => prev.map(msg => {
                            if (msg.id === aiMsgId) {
                                return { ...msg, content: fullReply, isLoading: true, webSearchStatus: null };
                            }
                            return msg;
                        }));
                    }
                },
                onWidgetUpdate: (widgetData) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId) || !widgetData?.tag) {
                        return;
                    }
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            return {
                                ...msg,
                                widgetUpdate: {
                                    tag: widgetData.tag,
                                    state: widgetData.state
                                }
                            };
                        }
                        return msg;
                    }));
                },
                onCanvasUpdate: (canvasUpdate) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                        return;
                    }
                    applyCanvasUpdate(canvasUpdate);
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            return {
                                ...msg,
                                canvasTextdoc: normalizeCanvasTextdoc(canvasUpdate?.textdoc),
                                canvasUpdates: [...(msg.canvasUpdates || []), canvasUpdate]
                            };
                        }
                        return msg;
                    }));
                },
                onComplete: (finalData) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                        return;
                    }
                    if (finalData?.aborted) {
                        fullReply += '\n\n_[Генерация остановлена]_';
                    }

                    const resolvedSessionId = finalData?.sessionId || sessionId;
                    const resolvedSlug = finalData?.sessionSlug
                        || (resolvedSessionId === currentSessionIdRef.current ? currentSessionSlugRef.current : null)
                        || sessionIdToSlug(resolvedSessionId);

                    if (!temporaryChat) {
                        syncSessionIdentity(resolvedSessionId, resolvedSlug, {
                            previousSessionId: sessionId,
                            historyMode: 'replace',
                            activate: currentSessionIdRef.current === sessionId
                        });
                    }

                    if (!temporaryChat && finalData?.session_token) {
                        storeGuestSessionToken(resolvedSessionId, finalData.session_token);
                    }

                    const finalContent = typeof finalData.reply === 'string' ? finalData.reply : fullReply;
                    const finalGitHubTool = finalData.github_tool || finalData.githubTool || null;
                    const finalCanvasTextdoc = normalizeCanvasTextdoc(finalData.canvas_textdoc || finalData.canvasTextdoc);
                    if (finalCanvasTextdoc) {
                        setCanvasTextdocState(finalCanvasTextdoc);
                    }
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            const firstVariant = {
                                content: finalContent,
                                images: finalData.images || [],
                                sources: finalData.sources || [],
                                githubTool: finalGitHubTool,
                                canvasTextdoc: finalCanvasTextdoc,
                                thinkingTime: finalData.thinkingTime
                            };
                            return {
                                ...msg,
                                isLoading: false,
                                isGeneratingImage: false,
                                webSearchStatus: null,
                                content: finalContent,
                                images: finalData.images || [],
                                sources: finalData.sources || [],
                                githubTool: finalGitHubTool,
                                canvasTextdoc: finalCanvasTextdoc,
                                canvasUpdates: Array.isArray(finalData.canvas_updates)
                                    ? finalData.canvas_updates
                                    : msg.canvasUpdates || [],
                                thinkingTime: finalData.thinkingTime,
                                variants: [firstVariant],
                                currentVariantIndex: 0
                            };
                        }
                        return msg;
                    }));
                    completeSessionRequest(sessionId, chatRequestId, finalData?.aborted ? null : 'complete');
                },
                onError: (err) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                        return;
                    }
                    console.error('Chat error', err);
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            return {
                                ...msg,
                                isLoading: false,
                                isGeneratingImage: false,
                                webSearchStatus: null,
                                isError: true,
                                content: `${fullReply}\n\n[Error: ${err?.message || 'unknown error'}]`
                            };
                        }
                        return msg;
                    }));
                    completeSessionRequest(sessionId, chatRequestId, 'error', err?.message || 'Generation failed');
                }
            });
        } catch (e) {
            if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                return;
            }
            if (e.name !== 'AbortError') {
                completeSessionRequest(sessionId, chatRequestId, 'error', e?.message || 'Generation failed');
            }
        }
    }, [
        addGuestSession,
        applyCanvasUpdate,
        beginSessionRequest,
        buildHistoryForAPI,
        completeSessionRequest,
        history,
        isSessionRequestCurrent,
        isReadOnly,
        registerSessionSlug,
        sessionIdToSlug,
        settings?.automaticWebSearch,
        setCanvasTextdocState,
        setTemporaryChatMode,
        storeGuestSessionToken,
        syncBrowserPath,
        syncPersistedCurrentSession,
        syncSessionIdentity,
        t,
        updateSessionHistory,
        upsertOptimisticSession,
        updateSessionIdentity
    ]);

    const stopGeneration = useCallback(() => {
        const sessionId = currentSessionIdRef.current;
        if (!sessionId) return;
        const controller = sessionAbortControllersRef.current.get(sessionId);
        if (controller) {
            controller.abort();
        }
    }, []);
    const regenerateMessage = useCallback(async (aiMessageId, model = 'gemini') => {
        if (isLoading || !aiMessageId) return;

        const aiIndex = history.findIndex(msg => msg.id === aiMessageId);
        if (aiIndex === -1) return;

        const userIndex = aiIndex - 1;
        if (userIndex < 0 || history[userIndex].role !== 'user') return;

        const userMessage = history[userIndex];
        const historyBefore = buildHistoryForAPI(userIndex);
        const sessionId = currentSessionIdRef.current || generateSessionId();
        const temporaryChat = temporaryChatRef.current;

        sessionLoadRequestIdRef.current += 1;
        sessionHistoryCacheRef.current.set(sessionId, history);
        const { requestId: chatRequestId, controller } = beginSessionRequest(sessionId);
        if (!temporaryChat) {
            upsertOptimisticSession(sessionId, userMessage.content, []);
        }

        updateSessionHistory(sessionId, prev => prev.map(msg => {
            if (msg.id === aiMessageId) {
                return { ...msg, isLoading: true, isError: false };
            }
            return msg;
        }));
        updateSessionHistory(sessionId, prev => prev.slice(0, aiIndex + 1));

        const formData = new FormData();
        formData.append('message', userMessage.content);
        formData.append('model', model);
        formData.append('session_id', sessionId);
        formData.append('history', JSON.stringify(historyBefore));
        if (canvasTextdocRef.current) {
            formData.append('canvas_textdoc', JSON.stringify(canvasTextdocRef.current));
        }
        if (beatboxStateRef.current) {
            formData.append('beatbox_state', JSON.stringify(beatboxStateRef.current));
        }
        formData.append('autoWebSearch', String(!!settings?.automaticWebSearch));
        formData.append('temporary_chat', String(temporaryChat));
        if (activeMindIdRef.current) {
            formData.append('mind_id', activeMindIdRef.current);
        }

        let fullReply = '';

        try {
            await apiService.chat(formData, controller.signal, {
                onPart: (data) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId) || !data?.reply_part) {
                        return;
                    }
                    fullReply += data.reply_part;
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMessageId) {
                            return { ...msg, content: fullReply, isLoading: true };
                        }
                        return msg;
                    }));
                },
                onWidgetUpdate: (widgetData) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId) || !widgetData?.tag) {
                        return;
                    }
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMessageId) {
                            return {
                                ...msg,
                                widgetUpdate: {
                                    tag: widgetData.tag,
                                    state: widgetData.state
                                }
                            };
                        }
                        return msg;
                    }));
                },
                onCanvasUpdate: (canvasUpdate) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                        return;
                    }
                    applyCanvasUpdate(canvasUpdate);
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMessageId) {
                            return {
                                ...msg,
                                canvasTextdoc: normalizeCanvasTextdoc(canvasUpdate?.textdoc),
                                canvasUpdates: [...(msg.canvasUpdates || []), canvasUpdate]
                            };
                        }
                        return msg;
                    }));
                },
                onComplete: (finalData) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                        return;
                    }
                    const finalGitHubTool = finalData.github_tool || finalData.githubTool || null;
                    const finalCanvasTextdoc = normalizeCanvasTextdoc(finalData.canvas_textdoc || finalData.canvasTextdoc);
                    if (finalCanvasTextdoc) {
                        setCanvasTextdocState(finalCanvasTextdoc);
                    }
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMessageId) {
                            const newVariant = {
                                content: typeof finalData.reply === 'string' ? finalData.reply : fullReply,
                                images: finalData.images || [],
                                sources: finalData.sources || [],
                                githubTool: finalGitHubTool,
                                canvasTextdoc: finalCanvasTextdoc,
                                thinkingTime: finalData.thinkingTime
                            };
                            const existingVariants = msg.variants || [];
                            const newVariants = [...existingVariants, newVariant];
                            const newCurrentIndex = newVariants.length - 1;

                            return {
                                ...msg,
                                isLoading: false,
                                content: newVariant.content,
                                images: newVariant.images,
                                sources: newVariant.sources,
                                githubTool: finalGitHubTool,
                                canvasTextdoc: finalCanvasTextdoc,
                                canvasUpdates: Array.isArray(finalData.canvas_updates)
                                    ? finalData.canvas_updates
                                    : msg.canvasUpdates || [],
                                thinkingTime: newVariant.thinkingTime,
                                variants: newVariants,
                                currentVariantIndex: newCurrentIndex
                            };
                        }
                        return msg;
                    }));
                    completeSessionRequest(sessionId, chatRequestId, finalData?.aborted ? null : 'complete');
                },
                onError: (err) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                        return;
                    }
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMessageId) {
                            return {
                                ...msg,
                                isLoading: false,
                                isError: true,
                                content: `${fullReply}\n\n[Error: ${err?.message || 'unknown error'}]`
                            };
                        }
                        return msg;
                    }));
                    completeSessionRequest(sessionId, chatRequestId, 'error', err?.message || 'Generation failed');
                }
            });
        } catch (e) {
            if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                return;
            }
            if (e.name !== 'AbortError') {
                completeSessionRequest(sessionId, chatRequestId, 'error', e?.message || 'Generation failed');
            }
        }
    }, [
        applyCanvasUpdate,
        beginSessionRequest,
        buildHistoryForAPI,
        completeSessionRequest,
        history,
        isLoading,
        isSessionRequestCurrent,
        settings?.automaticWebSearch,
        setCanvasTextdocState,
        updateSessionHistory,
        upsertOptimisticSession
    ]);
    const switchVariant = useCallback((aiMessageId, direction) => {
        setHistory(prev => {
            const aiIndex = prev.findIndex(msg => msg.id === aiMessageId);
            if (aiIndex === -1) return prev;

            const msg = prev[aiIndex];
            if (!msg.variants || msg.variants.length <= 1) return prev;

            const currentIndex = msg.currentVariantIndex || 0;
            const newIndex = currentIndex + direction;

            if (newIndex < 0 || newIndex >= msg.variants.length) return prev;

            const newVariant = msg.variants[newIndex];
            const newHistory = prev.slice(0, aiIndex + 1);
            return newHistory.map((m, idx) => {
                if (idx === aiIndex) {
                    return {
                        ...m,
                        content: newVariant.content,
                        images: newVariant.images || [],
                        sources: newVariant.sources || [],
                        githubTool: newVariant.githubTool || null,
                        thinkingTime: newVariant.thinkingTime,
                        currentVariantIndex: newIndex
                    };
                }
                return m;
            });
        });
    }, []);
    const editMessage = useCallback(async (userMessageId, newText, model = 'gemini') => {
        if (isLoading || !userMessageId || !newText?.trim() || isReadOnly) return;

        const userIndex = history.findIndex(msg => msg.id === userMessageId);
        if (userIndex === -1 || history[userIndex].role !== 'user') return;
        const sessionId = currentSessionIdRef.current || generateSessionId();
        const temporaryChat = temporaryChatRef.current;

        sessionLoadRequestIdRef.current += 1;
        sessionHistoryCacheRef.current.set(sessionId, history);
        const { requestId: chatRequestId, controller } = beginSessionRequest(sessionId);
        if (!temporaryChat) {
            upsertOptimisticSession(sessionId, newText, []);
        }

        updateSessionHistory(sessionId, prev => prev.map(msg => {
            if (msg.id === userMessageId) {
                return { ...msg, content: newText };
            }
            return msg;
        }));
        updateSessionHistory(sessionId, prev => {
            const newHistory = [];
            for (let i = 0; i < prev.length; i++) {
                if (i <= userIndex) {
                    newHistory.push(prev[i]);
                }
            }
            return newHistory;
        });
        const aiMsgId = `ai-${Date.now()}`;
        const aiMsg = {
            id: aiMsgId,
            role: 'model',
            content: '',
            isLoading: true,
            timestamp: Date.now() / 1000
        };

        updateSessionHistory(sessionId, prev => [...prev, aiMsg]);

        const historyBefore = buildHistoryForAPI(userIndex);
        const formData = new FormData();
        formData.append('message', newText);
        formData.append('model', model);
        formData.append('session_id', sessionId);
        formData.append('history', JSON.stringify(historyBefore));
        if (canvasTextdocRef.current) {
            formData.append('canvas_textdoc', JSON.stringify(canvasTextdocRef.current));
        }
        if (beatboxStateRef.current) {
            formData.append('beatbox_state', JSON.stringify(beatboxStateRef.current));
        }
        formData.append('autoWebSearch', String(!!settings?.automaticWebSearch));
        formData.append('temporary_chat', String(temporaryChat));
        if (activeMindIdRef.current) {
            formData.append('mind_id', activeMindIdRef.current);
        }

        let fullReply = '';

        try {
            await apiService.chat(formData, controller.signal, {
                onPart: (data) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId) || !data?.reply_part) {
                        return;
                    }
                    fullReply += data.reply_part;
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            return { ...msg, content: fullReply, isLoading: true };
                        }
                        return msg;
                    }));
                },
                onWidgetUpdate: (widgetData) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId) || !widgetData?.tag) {
                        return;
                    }
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            return {
                                ...msg,
                                widgetUpdate: {
                                    tag: widgetData.tag,
                                    state: widgetData.state
                                }
                            };
                        }
                        return msg;
                    }));
                },
                onCanvasUpdate: (canvasUpdate) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                        return;
                    }
                    applyCanvasUpdate(canvasUpdate);
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            return {
                                ...msg,
                                canvasTextdoc: normalizeCanvasTextdoc(canvasUpdate?.textdoc),
                                canvasUpdates: [...(msg.canvasUpdates || []), canvasUpdate]
                            };
                        }
                        return msg;
                    }));
                },
                onComplete: (finalData) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                        return;
                    }
                    const finalGitHubTool = finalData.github_tool || finalData.githubTool || null;
                    const finalCanvasTextdoc = normalizeCanvasTextdoc(finalData.canvas_textdoc || finalData.canvasTextdoc);
                    if (finalCanvasTextdoc) {
                        setCanvasTextdocState(finalCanvasTextdoc);
                    }
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            return {
                                ...msg,
                                isLoading: false,
                                content: typeof finalData.reply === 'string' ? finalData.reply : fullReply,
                                images: finalData.images || [],
                                sources: finalData.sources || [],
                                githubTool: finalGitHubTool,
                                canvasTextdoc: finalCanvasTextdoc,
                                canvasUpdates: Array.isArray(finalData.canvas_updates)
                                    ? finalData.canvas_updates
                                    : msg.canvasUpdates || []
                            };
                        }
                        return msg;
                    }));
                    completeSessionRequest(sessionId, chatRequestId, finalData?.aborted ? null : 'complete');
                },
                onError: (err) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                        return;
                    }
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            return {
                                ...msg,
                                isLoading: false,
                                isError: true,
                                content: `${fullReply}\n\n[Error: ${err?.message || 'unknown error'}]`
                            };
                        }
                        return msg;
                    }));
                    completeSessionRequest(sessionId, chatRequestId, 'error', err?.message || 'Generation failed');
                }
            });
        } catch (e) {
            if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                return;
            }
            if (e.name !== 'AbortError') {
                completeSessionRequest(sessionId, chatRequestId, 'error', e?.message || 'Generation failed');
            }
        }
    }, [
        applyCanvasUpdate,
        beginSessionRequest,
        buildHistoryForAPI,
        completeSessionRequest,
        history,
        isLoading,
        isReadOnly,
        isSessionRequestCurrent,
        settings?.automaticWebSearch,
        setCanvasTextdocState,
        updateSessionHistory,
        upsertOptimisticSession
    ]);

    const enableSharing = useCallback(async () => {
        const sessionId = currentSessionIdRef.current;
        if (temporaryChatRef.current) return null;
        if (!sessionId) return null;
        const data = await apiService.toggleShare(sessionId, true);
        const resolvedSessionId = data?.session_id || sessionId;
        const slug = data?.public_id || sessionIdToSlug(resolvedSessionId);
        const accessState = {
            isPublic: !!data?.is_public,
            isOwner: true,
            publicId: data?.public_id || null,
            shareUrl: data?.share_url || (data?.public_id ? `${window.location.origin}/c/${data.public_id}` : null),
            readOnly: false
        };
        setSessionAccess(accessState);
        setIsReadOnly(accessState.readOnly);
        syncSessionIdentity(resolvedSessionId, slug, {
            previousSessionId: sessionId,
            historyMode: 'replace',
            persistToGuestHistory: false
        });
        return data;
    }, [sessionIdToSlug, syncSessionIdentity]);

    const disableSharing = useCallback(async () => {
        const sessionId = currentSessionIdRef.current;
        if (temporaryChatRef.current) return null;
        if (!sessionId) return null;
        const data = await apiService.toggleShare(sessionId, false);
        const resolvedSessionId = data?.session_id || sessionId;
        const slug = sessionIdToSlug(resolvedSessionId);
        const accessState = {
            isPublic: false,
            isOwner: true,
            publicId: data?.public_id || null,
            shareUrl: null,
            readOnly: false
        };
        setSessionAccess(accessState);
        setIsReadOnly(false);
        syncSessionIdentity(resolvedSessionId, slug, {
            previousSessionId: sessionId,
            historyMode: 'replace',
            persistToGuestHistory: false
        });
        return data;
    }, [sessionIdToSlug, syncSessionIdentity]);

    return {
        history,
        canvasTextdoc,
        beatboxState,
        isLoading,
        currentSessionId,
        currentSessionSlug,
        sessionAccess,
        isReadOnly,
        isTemporaryChat,
        sessionActivity,
        optimisticSessions,
        loadSession,
        clearChat,
        startTemporaryChat,
        markSessionActivitySeen,
        setActiveSessionMindId,
        sendMessage,
        stopGeneration,
        regenerateMessage,
        editMessage,
        switchVariant,
        updateCanvasTextdocContent,
        updateBeatboxState,
        enableSharing,
        disableSharing,
        buildHistoryForAPI
    };
};
