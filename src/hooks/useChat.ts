import { useState, useRef, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { apiService, type CanvasTextdoc, type CanvasUpdate } from '../services/api';
import { fileService } from '../services/fileService';
import { ALLOW_GUEST_CHATS_SAVE } from '../utils/constants';
import { useSettings } from '../context/SettingsContext';
import { useAuth } from '../context/AuthContext';
import {
    enqueueChatMessage,
    listQueuedChatMessages,
    reconcileQueuedChatOwner,
    removeQueuedChatMessage,
} from '../services/reliability';

const DEFAULT_SESSION_ACCESS = {
    isPublic: false,
    isOwner: false,
    publicId: null,
    shareUrl: null,
    readOnly: false
};
const MAX_TEMPORARY_CHAT_VARIANTS = 50;

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
    thinkingLevel?: string;
    _fromQueue?: boolean;
    _forcedSessionId?: string;
    _queueId?: string;
    _queuedHistory?: unknown[];
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

function appendModelIfSelected(formData, model) {
    const selectedModel = typeof model === 'string' ? model.trim() : '';
    if (selectedModel) {
        formData.append('model', selectedModel);
    }
}

const VALID_THINKING_LEVELS = new Set(['minimal', 'low', 'medium', 'high']);

function appendThinkingLevelIfValid(formData: FormData, value: unknown) {
    const thinkingLevel = String(value || '').trim().toLowerCase();
    if (VALID_THINKING_LEVELS.has(thinkingLevel)) {
        formData.append('thinkingLevel', thinkingLevel);
    }
}

function isWebSearchStreamStatus(status) {
    return typeof status === 'string' && (
        status.startsWith('web_search_') ||
        status === 'generating_text'
    );
}

function isLocalPreviewUrl(value) {
    return typeof value === 'string' && (
        value.startsWith('blob:') ||
        value.startsWith('data:')
    );
}

async function getImageUploadMime(file) {
    const knownImageMime = fileService.getImageMimeType(file);
    if (knownImageMime) {
        return knownImageMime;
    }
    return fileService.detectImageMimeFromFile(file);
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

function normalizeHistoryVariant(value) {
    if (!value || typeof value !== 'object') return null;
    const parts = Array.isArray(value.parts) ? value.parts : [];
    const content = typeof value.content === 'string'
        ? value.content
        : (parts.find((part) => typeof part?.text === 'string')?.text || '');
    return {
        id: value.variant_id || value.id || crypto.randomUUID(),
        variantId: value.variant_id || value.id || null,
        content,
        images: parts.filter((part) => part?.image).map((part) => part.image.url_path || part.image),
        files: parts.filter((part) => part?.file).map((part) => ({ file: part.file })),
        sources: Array.isArray(value.sources) ? value.sources : [],
        githubTool: value.github_tool || value.githubTool || null,
        canvasTextdoc: normalizeCanvasTextdoc(value.canvas_textdoc || value.canvasTextdoc),
        canvasUpdates: Array.isArray(value.canvas_updates || value.canvasUpdates)
            ? (value.canvas_updates || value.canvasUpdates)
            : [],
        thinkingTime: value.thinkingTime,
        timestamp: value.timestamp,
        deliveryState: value.delivery_status === 'interrupted' ? 'interrupted' : undefined,
        parts
    };
}

function patchMessageVariant(message, variantId, patch) {
    if (!Array.isArray(message?.variants) || !variantId) return message;
    return {
        ...message,
        variants: message.variants.map((variant) => (
            (variant.variantId || variant.id) === variantId
                ? { ...variant, ...patch }
                : variant
        )),
    };
}

const MAX_STREAMED_THINKING_CHARS = 64_000;

function patchThinkingUpdate(message, update) {
    if (!message || !update || typeof update !== 'object') {
        return message;
    }
    const id = String(update.id || '').slice(0, 160);
    if (!id) {
        return message;
    }
    const previous = message.thinking?.id === id ? message.thinking : null;
    const delta = typeof update.contentDelta === 'string' ? update.contentDelta : '';
    const content = `${previous?.content || ''}${delta}`.slice(0, MAX_STREAMED_THINKING_CHARS);
    const openTime = Number(update.openTime || previous?.openTime || 0);
    const closeTime = Number(update.closeTime || previous?.closeTime || 0);
    const status = update.status === 'complete' ? 'complete' : 'streaming';
    return {
        ...message,
        thinking: {
            id,
            status,
            content,
            openTime: Number.isFinite(openTime) ? openTime : 0,
            closeTime: Number.isFinite(closeTime) && closeTime > 0 ? closeTime : undefined,
        },
    };
}

export function normalizeHistoryMessage(msg) {
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

    const variants = Array.isArray(msg.variants)
        ? msg.variants.map(normalizeHistoryVariant).filter(Boolean)
        : [];
    const requestedVariantIndex = Number(msg.current_variant_index ?? msg.currentVariantIndex ?? 0);
    const currentVariantIndex = variants.length
        ? Math.max(0, Math.min(Number.isFinite(requestedVariantIndex) ? requestedVariantIndex : 0, variants.length - 1))
        : undefined;
    const currentVariant = currentVariantIndex !== undefined ? variants[currentVariantIndex] : null;

    return {
        id: msg.id || Math.random().toString(36).substr(2, 9),
        role: msg.role,
        content: currentVariant?.content ?? text.trim(),
        images: currentVariant?.images ?? images,
        files: currentVariant?.files?.length ? currentVariant.files : files,
        sources: currentVariant?.sources ?? (Array.isArray(msg.sources) ? msg.sources : []),
        githubTool: currentVariant?.githubTool || msg.github_tool || msg.githubTool || null,
        canvasTextdoc: currentVariant?.canvasTextdoc || normalizeCanvasTextdoc(msg.canvas_textdoc || msg.canvasTextdoc),
        canvasUpdates: currentVariant?.canvasUpdates ?? (
            Array.isArray(msg.canvas_updates || msg.canvasUpdates)
                ? (msg.canvas_updates || msg.canvasUpdates)
                : []
        ),
        timestamp: currentVariant?.timestamp ?? msg.timestamp,
        deliveryState: currentVariant?.deliveryState
            ?? (msg.delivery_status === 'interrupted' ? 'interrupted' : undefined),
        parts: currentVariant?.parts ?? parts,
        variants,
        currentVariantIndex
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
    const { isAuthenticated, user, loading: authLoading, checkAuth } = useAuth();
    const reliabilityOwnerKey = isAuthenticated && user?.id ? `user:${user.id}` : 'guest';
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
    const [connectionState, setConnectionState] = useState<'online' | 'offline' | 'reconnecting'> (
        typeof navigator !== 'undefined' && !navigator.onLine ? 'offline' : 'online'
    );
    const [queuedMessageCount, setQueuedMessageCount] = useState(0);
    const sessionActivityRef = useRef<Record<string, SessionActivity>>({});
    const sessionHistoryCacheRef = useRef(new Map());
    const sessionAbortControllersRef = useRef(new Map());
    const sessionRequestIdsRef = useRef(new Map());
    const nextChatRequestIdRef = useRef(0);
    const temporaryBranchTailsRef = useRef(new Map<string, unknown[]>());
    const slugIndexCacheRef = useRef({});
    const sessionLoadRequestIdRef = useRef(0);
    const currentSessionIdRef = useRef(null);
    const currentSessionSlugRef = useRef(null);
    const canvasTextdocRef = useRef<CanvasTextdoc | null>(null);
    const beatboxStateRef = useRef(null);
    const activeMindIdRef = useRef(null);
    const temporaryChatRef = useRef(false);
    const localPreviewUrlsRef = useRef(new Set<string>());
    const flushingQueueRef = useRef(false);
    const switchingVariantRef = useRef(false);
    const checkAuthRef = useRef(checkAuth);

    useEffect(() => {
        checkAuthRef.current = checkAuth;
    }, [checkAuth]);

    useEffect(() => {
        if (authLoading) return;
        let active = true;
        const refreshCount = () => reconcileQueuedChatOwner(reliabilityOwnerKey)
            .then(() => listQueuedChatMessages(reliabilityOwnerKey))
            .then((items) => {
                if (!active) return;
                setQueuedMessageCount(items.length);
                if (items.length > 0 && navigator.onLine) {
                    setConnectionState('reconnecting');
                }
            })
            .catch(() => undefined);
        const handleOffline = () => setConnectionState('offline');
        const handleOnline = () => {
            setConnectionState('reconnecting');
            void checkAuthRef.current();
        };
        refreshCount();
        window.addEventListener('offline', handleOffline);
        window.addEventListener('online', handleOnline);
        return () => {
            active = false;
            window.removeEventListener('offline', handleOffline);
            window.removeEventListener('online', handleOnline);
        };
    }, [authLoading, reliabilityOwnerKey]);

    const revokeLocalPreviewUrls = useCallback((urls = []) => {
        urls.forEach((url) => {
            if (typeof url === 'string' && url.startsWith('blob:') && localPreviewUrlsRef.current.has(url)) {
                URL.revokeObjectURL(url);
                localPreviewUrlsRef.current.delete(url);
            }
        });
    }, []);

    const createLocalPreviewUrl = useCallback((file, mimeType = '') => new Promise((resolve) => {
        if (typeof FileReader === 'undefined') {
            resolve('');
            return;
        }

        const reader = new FileReader();
        reader.onload = () => {
            const result = typeof reader.result === 'string' ? reader.result : '';
            resolve(fileService.normalizeImageDataUrl(result, mimeType));
        };
        reader.onerror = () => resolve('');
        reader.readAsDataURL(file);
    }), []);

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
        const preview = (String(text || '').trim() || filePreview || t('rail.newChat')).slice(0, 80);

        setOptimisticSessions((previous) => ({
            ...previous,
            [sessionId]: {
                session_id: sessionId,
                title: previous[sessionId]?.title || preview,
                last_message: preview,
                last_updated: Date.now() / 1000
            }
        }));
    }, [t]);

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
        revokeLocalPreviewUrls(Array.from(localPreviewUrlsRef.current));
        setHistory([]);
        setCanvasTextdocState(null);
        updateBeatboxState(null);
        updateSessionIdentity(null, null);
        setSessionAccess(createDefaultSessionAccess());
        setIsReadOnly(false);
        activeMindIdRef.current = null;
        temporaryBranchTailsRef.current.clear();
    }, [revokeLocalPreviewUrls, setCanvasTextdocState, updateBeatboxState, updateSessionIdentity]);

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
        revokeLocalPreviewUrls(Array.from(localPreviewUrlsRef.current));
    }, [revokeLocalPreviewUrls]);

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
            temporaryBranchTailsRef.current.clear();
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
        syncSessionIdentity,
        updateBeatboxState
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
                        if (fileInfo?.file?.url_path && !isLocalPreviewUrl(fileInfo.file.url_path)) {
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
                        if (!isLocalPreviewUrl(imgPath)) {
                            parts.push({
                                image: {
                                    url_path: imgPath
                                }
                            });
                        }
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
    const sendMessage = useCallback(async (text, files = [], model = '', options: SendMessageOptions = {}) => {
        const {
            webSearch = false,
            autoWebSearch: requestedAutoWebSearch,
            censorship = false,
            mindId = undefined,
            temporaryChat: requestedTemporaryChat,
            thinkingLevel,
            _fromQueue = false,
            _forcedSessionId,
            _queueId,
            _queuedHistory,
            ...metadata
        } = options;
        const autoWebSearch = requestedAutoWebSearch ?? !!settings?.automaticWebSearch;
        const temporaryChat = requestedTemporaryChat ?? temporaryChatRef.current;
        if ((!text || !text.trim()) && files.length === 0) return;
        if (isReadOnly && !_fromQueue) {
            console.warn('Attempt to send message in read-only chat is blocked.');
            return;
        }

        sessionLoadRequestIdRef.current += 1;
        let sessionId = _forcedSessionId || currentSessionIdRef.current;
        const path = window.location.pathname;
        const isNewChat = !_forcedSessionId && (path === '/' || !path.startsWith('/c/'));

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
        if (!navigator.onLine && !_fromQueue) {
            const queueId = crypto.randomUUID();
            if (temporaryChat) {
                updateSessionHistory(sessionId, (previous) => [...previous, {
                    id: `temporary-offline-${queueId}`,
                    role: 'model',
                    content: t('reliability.temporaryOffline'),
                    isError: true,
                    timestamp: Date.now() / 1000,
                }]);
                setConnectionState('offline');
                return { queued: false };
            }
            const queuedHistory = buildHistoryForAPI(history.length);
            try {
                await enqueueChatMessage({
                    id: queueId,
                    createdAt: Date.now(),
                    sessionId,
                    text,
                    model,
                    options: {
                        webSearch,
                        autoWebSearch,
                        censorship,
                        mindId,
                        temporaryChat,
                        thinkingLevel,
                        ...metadata,
                    },
                    files,
                    apiHistory: queuedHistory,
                    ownerKey: reliabilityOwnerKey,
                });
            } catch {
                updateSessionHistory(sessionId, (previous) => [...previous, {
                    id: `queue-error-${queueId}`,
                    role: 'model',
                    content: t('reliability.queueFull'),
                    isError: true,
                    timestamp: Date.now() / 1000,
                }]);
                return { queued: false };
            }
            const pendingMessage = {
                id: `queued-${queueId}`,
                role: 'user',
                content: text,
                files: files.map((file) => ({
                    file: {
                        original_name: file.name,
                        mime_type: file.type || 'application/octet-stream',
                        size: file.size || 0,
                    },
                })),
                timestamp: Date.now() / 1000,
                deliveryState: 'queued',
                queueId,
            };
            updateSessionHistory(sessionId, (previous) => [...previous, pendingMessage]);
            setQueuedMessageCount((count) => count + 1);
            setConnectionState('offline');
            if (!temporaryChat) upsertOptimisticSession(sessionId, text, files);
            return { queued: true, queueId };
        }
        sessionHistoryCacheRef.current.set(sessionId, history);
        const { requestId: chatRequestId, controller } = beginSessionRequest(sessionId);
        if (!temporaryChat) {
            upsertOptimisticSession(sessionId, text, files);
        }
        const optimisticImageUrls = [];
        const optimisticFiles = [];
        for (const file of files) {
            const imageMime = await getImageUploadMime(file);
            if (imageMime) {
                const previewUrl = await createLocalPreviewUrl(file, imageMime);
                if (previewUrl) {
                    optimisticImageUrls.push(previewUrl);
                }
                continue;
            }

            optimisticFiles.push({
                file: {
                    original_name: file.name,
                    mime_type: file.type || 'application/octet-stream',
                    size: file.size || 0
                }
            });
        }
        const userMessageId = `u_${crypto.randomUUID()}`;
        const assistantMessageId = `a_${crypto.randomUUID()}`;
        const userMsg = {
            id: userMessageId,
            role: 'user',
            content: text,
            images: optimisticImageUrls,
            files: optimisticFiles,
            localAttachments: temporaryChat ? files : [],
            timestamp: Date.now() / 1000
        };
        const aiMsgId = assistantMessageId;
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

        updateSessionHistory(sessionId, prev => [
            ...prev.filter((message) => !_queueId || message.queueId !== _queueId),
            userMsg,
            aiMsg,
        ]);

        const formData = new FormData();
        formData.append('message', text);
        appendModelIfSelected(formData, model);
        appendThinkingLevelIfValid(formData, thinkingLevel);
        formData.append('session_id', sessionId);
        formData.append('operation', 'send');
        formData.append('user_message_id', userMessageId);
        formData.append('assistant_message_id', assistantMessageId);
        const apiHistoryForDelivery = Array.isArray(_queuedHistory)
            ? _queuedHistory
            : buildHistoryForAPI(history.length);
        formData.append('history', JSON.stringify(apiHistoryForDelivery));
        const deliveryRequestId = _queueId || crypto.randomUUID();
        formData.append('request_id', deliveryRequestId);
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
            const personalizationFields = ['personalization_instructions', 'personalization_profession', 'personalization_more'];
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
        let deliverySucceeded = false;

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

                    if (data.thinking_update) {
                        updateSessionHistory(sessionId, prev => prev.map(msg => (
                            msg.id === aiMsgId ? patchThinkingUpdate(msg, data.thinking_update) : msg
                        )));
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
                onOpen: ({ sessionToken }) => {
                    if (sessionToken) {
                        storeGuestSessionToken(sessionId, sessionToken);
                    }
                    setConnectionState('online');
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
                    if (currentSessionIdRef.current === sessionId) {
                        applyCanvasUpdate(canvasUpdate);
                    }
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
                    deliverySucceeded = !finalData?.aborted;
                    if (finalData?.aborted) {
                        fullReply += `\n\n_${t('chat.generationStopped')}_`;
                    }

                    const resolvedSessionId = finalData?.sessionId || sessionId;
                    const isActiveSession = currentSessionIdRef.current === sessionId
                        || currentSessionIdRef.current === resolvedSessionId;
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
                    const uploadedFiles = Array.isArray(finalData.uploaded_files)
                        ? finalData.uploaded_files
                        : [];
                    const uploadedImages = uploadedFiles
                        .filter((file) => typeof file?.mime_type === 'string' && file.mime_type.startsWith('image/') && file.url_path)
                        .map((file) => file.url_path);
                    const uploadedNonImageFiles = uploadedFiles
                        .filter((file) => !(typeof file?.mime_type === 'string' && file.mime_type.startsWith('image/')))
                        .map((file) => ({ file }));
                    if (finalCanvasTextdoc && isActiveSession) {
                        setCanvasTextdocState(finalCanvasTextdoc);
                    }
                    if (!temporaryChat && Array.isArray(finalData.history) && finalData.history.length > 0) {
                        revokeLocalPreviewUrls(optimisticImageUrls);
                        const canonicalHistory = finalData.history.map(normalizeHistoryMessage);
                        updateSessionHistory(sessionId, canonicalHistory);
                        if (isActiveSession) {
                            setCanvasTextdocState(extractLatestCanvasTextdoc(canonicalHistory));
                            updateBeatboxState(extractLatestBeatboxState(canonicalHistory));
                        }
                        completeSessionRequest(sessionId, chatRequestId, finalData?.aborted ? null : 'complete');
                        if (_queueId && deliverySucceeded) {
                            void removeQueuedChatMessage(_queueId).then(() => {
                                setQueuedMessageCount((count) => Math.max(0, count - 1));
                            });
                        }
                        return;
                    }
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === userMsg.id && uploadedFiles.length > 0) {
                            revokeLocalPreviewUrls(msg.images || []);
                            return {
                                ...msg,
                                images: uploadedImages,
                                files: uploadedNonImageFiles
                            };
                        }
                        if (msg.id === aiMsgId) {
                            const firstVariant = {
                                content: finalContent,
                                images: finalData.images || [],
                                sources: finalData.sources || [],
                                githubTool: finalGitHubTool,
                                canvasTextdoc: finalCanvasTextdoc,
                                thinkingTime: finalData.thinkingTime,
                                deliveryState: finalData?.aborted ? 'interrupted' : undefined
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
                                deliveryState: firstVariant.deliveryState,
                                variants: [firstVariant],
                                currentVariantIndex: 0
                            };
                        }
                        return msg;
                    }));
                    completeSessionRequest(sessionId, chatRequestId, finalData?.aborted ? null : 'complete');
                    if (_queueId && deliverySucceeded) {
                        void removeQueuedChatMessage(_queueId).then(() => {
                            setQueuedMessageCount((count) => Math.max(0, count - 1));
                        });
                    }
                },
                onError: (err) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                        return;
                    }
                    console.error('Chat error', err);
                    const errorStatus = Number((err as Error & { status?: number })?.status || 0);
                    const isNetworkFailure = !navigator.onLine
                        || errorStatus >= 500
                        || /fetch|network|connection|offline|stream_interrupted/i.test(err?.message || '');
                    if (isNetworkFailure) setConnectionState(navigator.onLine ? 'reconnecting' : 'offline');
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            return {
                                ...msg,
                                isLoading: false,
                                isGeneratingImage: false,
                                webSearchStatus: null,
                                isError: !isNetworkFailure,
                                deliveryState: isNetworkFailure ? 'interrupted' : 'error',
                                content: fullReply || msg.content
                            };
                        }
                        return msg;
                    }));
                    completeSessionRequest(sessionId, chatRequestId, 'error', t('chat.generationFailed'));
                    if (isNetworkFailure) {
                        const recover = async () => {
                            const enqueueForRetry = async () => {
                                if (temporaryChat || _queueId) return false;
                                try {
                                    await enqueueChatMessage({
                                        id: deliveryRequestId,
                                        createdAt: Date.now(),
                                        sessionId,
                                        text,
                                        model,
                                        options: {
                                            webSearch,
                                            autoWebSearch,
                                            censorship,
                                            mindId,
                                            temporaryChat,
                                            ...metadata,
                                        },
                                        files,
                                        apiHistory: apiHistoryForDelivery,
                                        ownerKey: reliabilityOwnerKey,
                                    });
                                    setQueuedMessageCount((count) => count + 1);
                                    setConnectionState(navigator.onLine ? 'reconnecting' : 'offline');
                                    return true;
                                } catch {
                                    updateSessionHistory(sessionId, (previous) => previous.map((message) => (
                                        message.id === aiMsgId
                                            ? { ...message, isError: true, content: t('reliability.queueFull') }
                                            : message
                                    )));
                                    return false;
                                }
                            };
                            if (!navigator.onLine) {
                                await enqueueForRetry();
                                return;
                            }
                            for (let attempt = 0; attempt < 4; attempt += 1) {
                                try {
                                    const recovered = await apiService.getSessionHistory(sessionId);
                                    if (Array.isArray(recovered.history)) {
                                        const deliveryWasPersisted = recovered.history.some((message) => (
                                            message?.request_id === deliveryRequestId
                                        ));
                                        if (deliveryWasPersisted) {
                                            const normalized = recovered.history.map(normalizeHistoryMessage);
                                            sessionHistoryCacheRef.current.set(sessionId, normalized);
                                            if (currentSessionIdRef.current === sessionId) setHistory(normalized);
                                            setConnectionState('online');
                                            return;
                                        }
                                    }
                                } catch {
                                }
                                if (attempt < 3) {
                                    await new Promise((resolve) => window.setTimeout(
                                        resolve,
                                        750 * (attempt + 1)
                                    ));
                                }
                            }
                            const queued = await enqueueForRetry();
                            if (!queued) {
                                setConnectionState(navigator.onLine ? 'online' : 'offline');
                            }
                        };
                        void recover();
                    }
                }
            });
            return { queued: false, delivered: deliverySucceeded };
        } catch (e) {
            if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                return;
            }
            if (e.name !== 'AbortError') {
                completeSessionRequest(sessionId, chatRequestId, 'error', t('chat.generationFailed'));
            }
            return { queued: false, delivered: false };
        }
    }, [
        addGuestSession,
        applyCanvasUpdate,
        beginSessionRequest,
        buildHistoryForAPI,
        completeSessionRequest,
        createLocalPreviewUrl,
        history,
        isSessionRequestCurrent,
        isReadOnly,
        registerSessionSlug,
        reliabilityOwnerKey,
        sessionIdToSlug,
        settings?.automaticWebSearch,
        setCanvasTextdocState,
        setTemporaryChatMode,
        storeGuestSessionToken,
        revokeLocalPreviewUrls,
        syncBrowserPath,
        syncPersistedCurrentSession,
        syncSessionIdentity,
        t,
        updateBeatboxState,
        updateSessionHistory,
        upsertOptimisticSession,
        updateSessionIdentity
    ]);

    useEffect(() => {
        if (connectionState !== 'reconnecting' || flushingQueueRef.current) return;
        flushingQueueRef.current = true;
        void (async () => {
            try {
                const queued = await listQueuedChatMessages(reliabilityOwnerKey);
                for (const item of queued) {
                    if (!navigator.onLine) break;
                    const result = await sendMessage(item.text, item.files || [], item.model, {
                        ...item.options,
                        _fromQueue: true,
                        _forcedSessionId: item.sessionId,
                        _queueId: item.id,
                        _queuedHistory: item.apiHistory || [],
                    });
                    if (!result?.delivered) break;
                }
                setConnectionState(navigator.onLine ? 'online' : 'offline');
            } finally {
                flushingQueueRef.current = false;
            }
        })();
    }, [connectionState, reliabilityOwnerKey, sendMessage]);

    const stopGeneration = useCallback(() => {
        const sessionId = currentSessionIdRef.current;
        if (!sessionId) return;
        const controller = sessionAbortControllersRef.current.get(sessionId);
        if (controller) {
            controller.abort();
        }
    }, []);
    const regenerateMessage = useCallback(async (aiMessageId, model = '', thinkingLevel = '') => {
        if (isLoading || !aiMessageId) return;

        const aiIndex = history.findIndex(msg => msg.id === aiMessageId);
        if (aiIndex === -1) return;

        const userIndex = aiIndex - 1;
        if (userIndex < 0 || history[userIndex].role !== 'user') return;

        const userMessage = history[userIndex];
        const repeatWebSearch = Array.isArray(history[aiIndex].sources)
            && history[aiIndex].sources.length > 0;
        const historyBefore = buildHistoryForAPI(userIndex);
        const sessionId = currentSessionIdRef.current || generateSessionId();
        const temporaryChat = temporaryChatRef.current;
        if (
            temporaryChat &&
            Math.max(1, history[aiIndex].variants?.length || 0) >= MAX_TEMPORARY_CHAT_VARIANTS
        ) {
            setSessionActivityState(sessionId, 'error', t('chat.variantLimitReached'));
            return;
        }
        if (temporaryChat) {
            const currentVariant = Array.isArray(history[aiIndex].variants)
                ? history[aiIndex].variants[history[aiIndex].currentVariantIndex || 0]
                : null;
            const currentVariantId = currentVariant?.variantId || currentVariant?.id || aiMessageId;
            temporaryBranchTailsRef.current.set(
                currentVariantId,
                history.slice(aiIndex + 1)
            );
        }
        const assistantMessageId = `a_${crypto.randomUUID()}`;
        const deliveryRequestId = crypto.randomUUID();

        sessionLoadRequestIdRef.current += 1;
        sessionHistoryCacheRef.current.set(sessionId, history);
        const { requestId: chatRequestId, controller } = beginSessionRequest(sessionId);
        if (!temporaryChat) {
            upsertOptimisticSession(sessionId, userMessage.content, []);
        }

        updateSessionHistory(sessionId, prev => (
            temporaryChat ? prev.slice(0, aiIndex + 1) : prev
        ).map(msg => {
            if (msg.id === aiMessageId) {
                const baselineVariants = Array.isArray(msg.variants) && msg.variants.length
                    ? msg.variants
                    : [{
                        id: msg.id,
                        variantId: msg.id,
                        content: msg.content,
                        images: msg.images || [],
                        files: msg.files || [],
                        sources: msg.sources || [],
                        githubTool: msg.githubTool || null,
                        canvasTextdoc: msg.canvasTextdoc || null,
                        thinkingTime: msg.thinkingTime,
                    }];
                const pendingVariant = {
                    id: assistantMessageId,
                    variantId: assistantMessageId,
                    content: '',
                    images: [],
                    sources: [],
                };
                return {
                    ...msg,
                    content: '',
                    images: [],
                    sources: [],
                    variants: [...baselineVariants, pendingVariant],
                    currentVariantIndex: baselineVariants.length,
                    isLoading: true,
                    isError: false,
                };
            }
            return msg;
        }));
        const formData = new FormData();
        formData.append('message', userMessage.content);
        appendModelIfSelected(formData, model);
        appendThinkingLevelIfValid(formData, thinkingLevel);
        formData.append('session_id', sessionId);
        formData.append('operation', 'regenerate');
        formData.append('target_message_id', aiMessageId);
        formData.append('assistant_message_id', assistantMessageId);
        formData.append('request_id', deliveryRequestId);
        formData.append('history', JSON.stringify(historyBefore));
        if (canvasTextdocRef.current) {
            formData.append('canvas_textdoc', JSON.stringify(canvasTextdocRef.current));
        }
        if (beatboxStateRef.current) {
            formData.append('beatbox_state', JSON.stringify(beatboxStateRef.current));
        }
        formData.append('autoWebSearch', String(!!settings?.automaticWebSearch));
        formData.append('webSearch', String(repeatWebSearch));
        formData.append('temporary_chat', String(temporaryChat));
        if (activeMindIdRef.current) {
            formData.append('mind_id', activeMindIdRef.current);
        }
        if (temporaryChat && Array.isArray(userMessage.localAttachments)) {
            userMessage.localAttachments.forEach((file, index) => {
                formData.append(`file${index}`, file, file.name);
            });
        }

        let fullReply = '';

        try {
            await apiService.chat(formData, controller.signal, {
                onOpen: ({ sessionToken }) => {
                    if (sessionToken) storeGuestSessionToken(sessionId, sessionToken);
                },
                onPart: (data) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId) || !data) {
                        return;
                    }
                    if (data.thinking_update) {
                        updateSessionHistory(sessionId, prev => prev.map(msg => {
                            if (msg.id !== aiMessageId) {
                                return msg;
                            }
                            const updated = patchThinkingUpdate(msg, data.thinking_update);
                            return patchMessageVariant(updated, assistantMessageId, {
                                thinking: updated.thinking,
                            });
                        }));
                    }
                    if (!data.reply_part) {
                        return;
                    }
                    fullReply += data.reply_part;
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMessageId) {
                            return patchMessageVariant(
                                { ...msg, content: fullReply, isLoading: true },
                                assistantMessageId,
                                { content: fullReply }
                            );
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
                            return patchMessageVariant({
                                ...msg,
                                widgetUpdate: {
                                    tag: widgetData.tag,
                                    state: widgetData.state
                                }
                            }, assistantMessageId, {
                                widgetUpdate: {
                                    tag: widgetData.tag,
                                    state: widgetData.state
                                }
                            });
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
                            const nextCanvasUpdates = [...(msg.canvasUpdates || []), canvasUpdate];
                            return patchMessageVariant({
                                ...msg,
                                canvasTextdoc: normalizeCanvasTextdoc(canvasUpdate?.textdoc),
                                canvasUpdates: nextCanvasUpdates
                            }, assistantMessageId, {
                                canvasTextdoc: normalizeCanvasTextdoc(canvasUpdate?.textdoc),
                                canvasUpdates: nextCanvasUpdates
                            });
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
                    if (!temporaryChat && Array.isArray(finalData.history) && finalData.history.length > 0) {
                        const canonicalHistory = finalData.history.map(normalizeHistoryMessage);
                        updateSessionHistory(sessionId, canonicalHistory);
                        setCanvasTextdocState(extractLatestCanvasTextdoc(canonicalHistory));
                        updateBeatboxState(extractLatestBeatboxState(canonicalHistory));
                        completeSessionRequest(sessionId, chatRequestId, finalData?.aborted ? null : 'complete');
                        return;
                    }
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMessageId) {
                            const newVariant = {
                                id: assistantMessageId,
                                variantId: assistantMessageId,
                                content: typeof finalData.reply === 'string' ? finalData.reply : fullReply,
                                images: finalData.images || [],
                                sources: finalData.sources || [],
                                githubTool: finalGitHubTool,
                                canvasTextdoc: finalCanvasTextdoc,
                                thinkingTime: finalData.thinkingTime,
                                deliveryState: finalData?.aborted ? 'interrupted' : undefined
                            };
                            const existingVariants = msg.variants || [];
                            const pendingIndex = existingVariants.findIndex((variant) => (
                                (variant.variantId || variant.id) === assistantMessageId
                            ));
                            const newVariants = pendingIndex >= 0
                                ? existingVariants.map((variant, index) => (
                                    index === pendingIndex ? { ...variant, ...newVariant } : variant
                                ))
                                : [...existingVariants, newVariant];
                            const newCurrentIndex = pendingIndex >= 0
                                ? pendingIndex
                                : newVariants.length - 1;

                            return {
                                ...msg,
                                id: assistantMessageId,
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
                                deliveryState: newVariant.deliveryState,
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
                    if (!temporaryChat) {
                        updateSessionHistory(sessionId, history);
                        completeSessionRequest(sessionId, chatRequestId, 'error', t('chat.generationFailed'));
                        return;
                    }
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMessageId) {
                            const errorCode = (err as Error & {
                                data?: { error?: { code?: string } };
                            })?.data?.error?.code;
                            const errorContent = fullReply || (
                                errorCode === 'chat_variant_limit_reached'
                                    ? t('chat.variantLimitReached')
                                    : errorCode === 'message_id_conflict'
                                        ? t('chat.versionConflict')
                                        : t('chat.generationFailed')
                            );
                            return patchMessageVariant({
                                ...msg,
                                isLoading: false,
                                isError: true,
                                content: errorContent
                            }, assistantMessageId, { content: errorContent });
                        }
                        return msg;
                    }));
                    completeSessionRequest(sessionId, chatRequestId, 'error', t('chat.generationFailed'));
                }
            });
        } catch (e) {
            if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                return;
            }
            if (e.name !== 'AbortError') {
                completeSessionRequest(sessionId, chatRequestId, 'error', t('chat.generationFailed'));
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
        setSessionActivityState,
        storeGuestSessionToken,
        t,
        updateBeatboxState,
        updateSessionHistory,
        upsertOptimisticSession
    ]);
    const switchVariant = useCallback(async (messageId, direction) => {
        if (isLoading || switchingVariantRef.current) return;
        const messageIndex = history.findIndex((message) => message.id === messageId);
        if (messageIndex < 0) return;
        const message = history[messageIndex];
        if (!Array.isArray(message.variants) || message.variants.length <= 1) return;
        const currentIndex = message.currentVariantIndex || 0;
        const newIndex = currentIndex + direction;
        if (newIndex < 0 || newIndex >= message.variants.length) return;
        const selectedVariant = message.variants[newIndex];
        const selectedMessageId = selectedVariant.variantId || selectedVariant.id;
        const sessionId = currentSessionIdRef.current;

        if (sessionId && !temporaryChatRef.current && !isReadOnly && selectedMessageId) {
            switchingVariantRef.current = true;
            try {
                const response = await apiService.selectSessionBranch(sessionId, selectedMessageId);
                if (Array.isArray(response.history)) {
                    const canonicalHistory = response.history.map(normalizeHistoryMessage);
                    updateSessionHistory(sessionId, canonicalHistory);
                    setCanvasTextdocState(extractLatestCanvasTextdoc(canonicalHistory));
                    updateBeatboxState(extractLatestBeatboxState(canonicalHistory));
                    return;
                }
            } catch (error) {
                console.error('Failed to switch conversation branch', error);
                return;
            } finally {
                switchingVariantRef.current = false;
            }
        }

        const currentVariant = message.variants[currentIndex];
        const currentVariantId = currentVariant?.variantId || currentVariant?.id || message.id;
        temporaryBranchTailsRef.current.set(
            currentVariantId,
            history.slice(messageIndex + 1)
        );
        const selectedTail = (temporaryBranchTailsRef.current.get(selectedMessageId) || []) as typeof history;
        const localHistory = history.slice(0, messageIndex + 1).map((item, index) => {
            if (index !== messageIndex) return item;
            return {
                ...item,
                id: selectedMessageId || item.id,
                content: selectedVariant.content,
                images: selectedVariant.images || [],
                files: selectedVariant.files || item.files || [],
                sources: selectedVariant.sources || [],
                githubTool: selectedVariant.githubTool || null,
                canvasTextdoc: selectedVariant.canvasTextdoc || null,
                canvasUpdates: selectedVariant.canvasUpdates || [],
                thinkingTime: selectedVariant.thinkingTime,
                currentVariantIndex: newIndex,
                parts: selectedVariant.parts || item.parts,
            };
        }).concat(selectedTail);
        if (sessionId) updateSessionHistory(sessionId, localHistory);
        else setHistory(localHistory);
        setCanvasTextdocState(extractLatestCanvasTextdoc(localHistory));
        updateBeatboxState(extractLatestBeatboxState(localHistory));
    }, [
        history,
        isLoading,
        isReadOnly,
        setCanvasTextdocState,
        updateBeatboxState,
        updateSessionHistory,
    ]);
    const editMessage = useCallback(async (
        userMessageId,
        newText,
        model = '',
        thinkingLevel = '',
    ) => {
        if (isLoading || !userMessageId || !newText?.trim() || isReadOnly) return;

        const userIndex = history.findIndex(msg => msg.id === userMessageId);
        if (userIndex === -1 || history[userIndex].role !== 'user') return;
        const sessionId = currentSessionIdRef.current || generateSessionId();
        const temporaryChat = temporaryChatRef.current;
        if (
            temporaryChat &&
            Math.max(1, history[userIndex].variants?.length || 0) >= MAX_TEMPORARY_CHAT_VARIANTS
        ) {
            setSessionActivityState(sessionId, 'error', t('chat.variantLimitReached'));
            return;
        }
        if (temporaryChat) {
            const currentVariant = Array.isArray(history[userIndex].variants)
                ? history[userIndex].variants[history[userIndex].currentVariantIndex || 0]
                : null;
            const currentVariantId = currentVariant?.variantId || currentVariant?.id || userMessageId;
            temporaryBranchTailsRef.current.set(
                currentVariantId,
                history.slice(userIndex + 1)
            );
        }
        const repeatWebSearch = Array.isArray(history[userIndex + 1]?.sources)
            && history[userIndex + 1].sources.length > 0;
        const editedUserMessageId = `u_${crypto.randomUUID()}`;
        const assistantMessageId = `a_${crypto.randomUUID()}`;
        const deliveryRequestId = crypto.randomUUID();

        sessionLoadRequestIdRef.current += 1;
        sessionHistoryCacheRef.current.set(sessionId, history);
        const { requestId: chatRequestId, controller } = beginSessionRequest(sessionId);
        if (!temporaryChat) {
            upsertOptimisticSession(sessionId, newText, []);
        }

        updateSessionHistory(sessionId, prev => prev.map(msg => {
            if (msg.id === userMessageId) {
                const baselineVariants = Array.isArray(msg.variants) && msg.variants.length
                    ? msg.variants
                    : [{
                        id: msg.id,
                        variantId: msg.id,
                        content: msg.content,
                        images: msg.images || [],
                        files: msg.files || [],
                        sources: [],
                    }];
                const editedVariant = {
                    id: editedUserMessageId,
                    variantId: editedUserMessageId,
                    content: newText,
                    images: msg.images || [],
                    files: msg.files || [],
                    sources: [],
                };
                return {
                    ...msg,
                    content: newText,
                    variants: [...baselineVariants, editedVariant],
                    currentVariantIndex: baselineVariants.length,
                };
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
        const aiMsgId = assistantMessageId;
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
        appendModelIfSelected(formData, model);
        appendThinkingLevelIfValid(formData, thinkingLevel);
        formData.append('session_id', sessionId);
        formData.append('operation', 'edit');
        formData.append('target_message_id', userMessageId);
        formData.append('user_message_id', editedUserMessageId);
        formData.append('assistant_message_id', assistantMessageId);
        formData.append('request_id', deliveryRequestId);
        formData.append('history', JSON.stringify(historyBefore));
        if (canvasTextdocRef.current) {
            formData.append('canvas_textdoc', JSON.stringify(canvasTextdocRef.current));
        }
        if (beatboxStateRef.current) {
            formData.append('beatbox_state', JSON.stringify(beatboxStateRef.current));
        }
        formData.append('autoWebSearch', String(!!settings?.automaticWebSearch));
        formData.append('webSearch', String(repeatWebSearch));
        formData.append('temporary_chat', String(temporaryChat));
        if (activeMindIdRef.current) {
            formData.append('mind_id', activeMindIdRef.current);
        }
        const editedMessageAttachments = history[userIndex].localAttachments;
        if (temporaryChat && Array.isArray(editedMessageAttachments)) {
            editedMessageAttachments.forEach((file, index) => {
                formData.append(`file${index}`, file, file.name);
            });
        }

        let fullReply = '';

        try {
            await apiService.chat(formData, controller.signal, {
                onOpen: ({ sessionToken }) => {
                    if (sessionToken) storeGuestSessionToken(sessionId, sessionToken);
                },
                onPart: (data) => {
                    if (!isSessionRequestCurrent(sessionId, chatRequestId) || !data) {
                        return;
                    }
                    if (data.thinking_update) {
                        updateSessionHistory(sessionId, prev => prev.map(msg => (
                            msg.id === aiMsgId ? patchThinkingUpdate(msg, data.thinking_update) : msg
                        )));
                    }
                    if (!data.reply_part) {
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
                    if (!temporaryChat && Array.isArray(finalData.history) && finalData.history.length > 0) {
                        const canonicalHistory = finalData.history.map(normalizeHistoryMessage);
                        updateSessionHistory(sessionId, canonicalHistory);
                        setCanvasTextdocState(extractLatestCanvasTextdoc(canonicalHistory));
                        updateBeatboxState(extractLatestBeatboxState(canonicalHistory));
                        completeSessionRequest(sessionId, chatRequestId, finalData?.aborted ? null : 'complete');
                        return;
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
                                    : msg.canvasUpdates || [],
                                deliveryState: finalData?.aborted ? 'interrupted' : undefined
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
                    if (!temporaryChat) {
                        updateSessionHistory(sessionId, history);
                        completeSessionRequest(sessionId, chatRequestId, 'error', t('chat.generationFailed'));
                        return;
                    }
                    updateSessionHistory(sessionId, prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            const errorCode = (err as Error & {
                                data?: { error?: { code?: string } };
                            })?.data?.error?.code;
                            return {
                                ...msg,
                                isLoading: false,
                                isError: true,
                                content: fullReply || (
                                    errorCode === 'chat_variant_limit_reached'
                                        ? t('chat.variantLimitReached')
                                        : errorCode === 'message_id_conflict'
                                            ? t('chat.versionConflict')
                                            : t('chat.generationFailed')
                                )
                            };
                        }
                        return msg;
                    }));
                    completeSessionRequest(sessionId, chatRequestId, 'error', t('chat.generationFailed'));
                }
            });
        } catch (e) {
            if (!isSessionRequestCurrent(sessionId, chatRequestId)) {
                return;
            }
            if (e.name !== 'AbortError') {
                completeSessionRequest(sessionId, chatRequestId, 'error', t('chat.generationFailed'));
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
        setSessionActivityState,
        storeGuestSessionToken,
        t,
        updateBeatboxState,
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
        connectionState,
        queuedMessageCount,
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
