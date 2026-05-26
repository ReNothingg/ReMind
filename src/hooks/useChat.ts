import { useState, useRef, useCallback, useEffect } from 'react';
import { apiService } from '../services/api';
import { ALLOW_GUEST_CHATS_SAVE } from '../utils/constants';

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
};

type LoadSessionOptions = {
    historyMode?: HistoryMode;
    clearHistory?: boolean;
};

type ClearChatOptions = {
    historyMode?: HistoryMode;
};

type SendMessageOptions = {
    webSearch?: boolean;
    censorship?: boolean;
    mindId?: string | null;
    [key: string]: unknown;
};

function createDefaultSessionAccess() {
    return { ...DEFAULT_SESSION_ACCESS };
}

function generateSessionId() {
    return crypto.randomUUID();
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
        timestamp: msg.timestamp,
        parts
    };
}

export const useChat = () => {
    const [history, setHistory] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [currentSessionId, setCurrentSessionId] = useState(null);
    const [currentSessionSlug, setCurrentSessionSlug] = useState(null);
    const [sessionAccess, setSessionAccess] = useState(createDefaultSessionAccess);
    const [isReadOnly, setIsReadOnly] = useState(false);
    const abortControllerRef = useRef(null);
    const messageVariantsRef = useRef(new Map());
    const slugIndexCacheRef = useRef({});
    const sessionLoadRequestIdRef = useRef(0);
    const activeChatRequestIdRef = useRef(0);
    const currentSessionIdRef = useRef(null);
    const currentSessionSlugRef = useRef(null);
    const activeMindIdRef = useRef(null);

    const updateSessionIdentity = useCallback((sessionId, slug) => {
        currentSessionIdRef.current = sessionId;
        currentSessionSlugRef.current = slug;
        setCurrentSessionId(sessionId);
        setCurrentSessionSlug(slug);
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

    const resetConversationState = useCallback(() => {
        setHistory([]);
        updateSessionIdentity(null, null);
        setSessionAccess(createDefaultSessionAccess());
        setIsReadOnly(false);
        activeMindIdRef.current = null;
        messageVariantsRef.current.clear();
    }, [updateSessionIdentity]);

    const abortActiveChatRequest = useCallback((invalidate = false) => {
        if (invalidate) {
            activeChatRequestIdRef.current += 1;
        }
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
            abortControllerRef.current = null;
        }
    }, []);

    const syncSessionIdentity = useCallback((sessionId, slug, options: SyncSessionOptions = {}) => {
        if (!sessionId) return;

        const {
            previousSessionId = null,
            historyMode = 'replace',
            persistToGuestHistory = true
        } = options;

        updateSessionIdentity(sessionId, slug);
        registerSessionSlug(sessionId, slug);
        syncPersistedCurrentSession(sessionId, slug);

        if (persistToGuestHistory) {
            addGuestSession(sessionId);
            if (previousSessionId && previousSessionId !== sessionId) {
                removeGuestSession(previousSessionId);
                removeGuestSessionToken(previousSessionId);
            }
        }

        syncBrowserPath(`/c/${encodeURIComponent(slug)}`, historyMode);
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
        abortActiveChatRequest(true);
    }, [abortActiveChatRequest]);

    const loadSession = useCallback(async (sessionIdOrSlug, options: LoadSessionOptions = {}) => {
        const { historyMode = 'replace', clearHistory = true } = options;
        const loadRequestId = sessionLoadRequestIdRef.current + 1;
        sessionLoadRequestIdRef.current = loadRequestId;
        activeMindIdRef.current = null;

        abortActiveChatRequest(true);
        setIsLoading(true);

        if (clearHistory) {
            setHistory([]);
            setSessionAccess(createDefaultSessionAccess());
            setIsReadOnly(false);
            messageVariantsRef.current.clear();
        }

        try {
            const requestedSessionId = slugToSessionId(sessionIdOrSlug);
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
                setSessionAccess(accessState);
                setIsReadOnly(accessState.readOnly);
                activeMindIdRef.current = data.mind?.public_id || null;
                syncSessionIdentity(resolvedSessionId, slug, { historyMode });
                return data;
            }

            resetConversationState();
            syncPersistedCurrentSession(null, null);
            syncBrowserPath('/', 'replace');
            return null;
        } catch (e) {
            if (sessionLoadRequestIdRef.current !== loadRequestId) {
                return;
            }

            console.error('Failed to load session', e);
            resetConversationState();
            syncPersistedCurrentSession(null, null);
            syncBrowserPath('/', 'replace');
            return null;
        } finally {
            if (sessionLoadRequestIdRef.current === loadRequestId) {
                setIsLoading(false);
            }
        }
    }, [
        abortActiveChatRequest,
        resetConversationState,
        sessionIdToSlug,
        slugToSessionId,
        syncBrowserPath,
        syncPersistedCurrentSession,
        syncSessionIdentity
    ]);

    const clearChat = useCallback((options: ClearChatOptions = {}) => {
        const { historyMode = 'push' } = options;
        sessionLoadRequestIdRef.current += 1;
        abortActiveChatRequest(true);
        resetConversationState();
        syncPersistedCurrentSession(null, null);
        setIsLoading(false);
        syncBrowserPath('/', historyMode);
    }, [abortActiveChatRequest, resetConversationState, syncBrowserPath, syncPersistedCurrentSession]);

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
                historyArray.push({
                    role: isUser ? 'user' : 'model',
                    parts: parts
                });
            }
        }
        return historyArray;
    }, [history]);
    const sendMessage = useCallback(async (text, files = [], model = 'gemini', options: SendMessageOptions = {}) => {
        const { webSearch = false, censorship = false, mindId = undefined, ...metadata } = options;
        if ((!text || !text.trim()) && files.length === 0) return;
        if (isReadOnly) {
            console.warn('Attempt to send message in read-only chat is blocked.');
            return;
        }

        sessionLoadRequestIdRef.current += 1;

        const chatRequestId = activeChatRequestIdRef.current + 1;
        activeChatRequestIdRef.current = chatRequestId;

        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
        }
        abortControllerRef.current = new AbortController();
        setIsLoading(true);
        let sessionId = currentSessionIdRef.current;
        const path = window.location.pathname;
        const isNewChat = path === '/' || !path.startsWith('/c/');

        if (!sessionId || isNewChat) {
            sessionId = generateSessionId();
            const slug = sessionIdToSlug(sessionId);
            updateSessionIdentity(sessionId, slug);
            setSessionAccess(createDefaultSessionAccess());
            setIsReadOnly(false);
            registerSessionSlug(sessionId, slug);
            syncPersistedCurrentSession(sessionId, slug);
            addGuestSession(sessionId);

            if (isNewChat) {
                syncBrowserPath(`/c/${encodeURIComponent(slug)}`, 'push');
            }
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
            timestamp: Date.now() / 1000
        };

        setHistory(prev => [...prev, userMsg, aiMsg]);

        const formData = new FormData();
        formData.append('message', text);
        formData.append('model', model);
        formData.append('session_id', sessionId);
        formData.append('history', JSON.stringify(buildHistoryForAPI(history.length)));
        formData.append('webSearch', String(webSearch));
        formData.append('censorship', String(censorship));
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
            await apiService.chat(formData, abortControllerRef.current.signal, {
                onPart: (data) => {
                    if (activeChatRequestIdRef.current !== chatRequestId || !data) return;
                    if (data.status === 'generating_image') {
                        setHistory(prev => prev.map(msg => {
                            if (msg.id === aiMsgId) {
                                return { ...msg, isGeneratingImage: true, imagePrompt: data.prompt };
                            }
                            return msg;
                        }));
                        firstChunk = false;
                        return;
                    }

                    if (data.reply_part || data.images) {
                        setHistory(prev => prev.map(msg => {
                            if (msg.id === aiMsgId) {
                                return { ...msg, isGeneratingImage: false };
                            }
                            return msg;
                        }));
                    }

                    if (firstChunk) {
                        setHistory(prev => prev.map(msg => {
                            if (msg.id === aiMsgId) {
                                return { ...msg, isGeneratingImage: false };
                            }
                            return msg;
                        }));
                        firstChunk = false;
                    }

                    if (data.images) {
                        setHistory(prev => prev.map(msg => {
                            if (msg.id === aiMsgId) {
                                return { ...msg, images: data.images, isLoading: true };
                            }
                            return msg;
                        }));
                    }

                    if (data.reply_part) {
                        fullReply += data.reply_part;
                        setHistory(prev => prev.map(msg => {
                            if (msg.id === aiMsgId) {
                                return { ...msg, content: fullReply, isLoading: true };
                            }
                            return msg;
                        }));
                    }
                },
                onWidgetUpdate: (widgetData) => {
                    if (activeChatRequestIdRef.current !== chatRequestId || !widgetData?.tag) {
                        return;
                    }
                    setHistory(prev => prev.map(msg => {
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
                onComplete: (finalData) => {
                    if (activeChatRequestIdRef.current !== chatRequestId) {
                        return;
                    }
                    if (finalData?.aborted) {
                        fullReply += '\n\n_[Генерация остановлена]_';
                    }

                    const resolvedSessionId = finalData?.sessionId || sessionId;
                    const resolvedSlug = finalData?.sessionSlug
                        || (resolvedSessionId === currentSessionIdRef.current ? currentSessionSlugRef.current : null)
                        || sessionIdToSlug(resolvedSessionId);

                    syncSessionIdentity(resolvedSessionId, resolvedSlug, {
                        previousSessionId: sessionId,
                        historyMode: 'replace'
                    });

                    if (finalData?.session_token) {
                        storeGuestSessionToken(resolvedSessionId, finalData.session_token);
                    }

                    const finalContent = finalData.reply || fullReply;
                    setHistory(prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            const firstVariant = {
                                content: finalContent,
                                images: finalData.images || [],
                                sources: finalData.sources || [],
                                thinkingTime: finalData.thinkingTime
                            };
                            return {
                                ...msg,
                                isLoading: false,
                                isGeneratingImage: false,
                                content: finalContent,
                                images: finalData.images || [],
                                sources: finalData.sources || [],
                                thinkingTime: finalData.thinkingTime,
                                variants: [firstVariant],
                                currentVariantIndex: 0
                            };
                        }
                        return msg;
                    }));
                    abortControllerRef.current = null;
                    setIsLoading(false);
                },
                onError: (err) => {
                    if (activeChatRequestIdRef.current !== chatRequestId) {
                        return;
                    }
                    console.error('Chat error', err);
                    setHistory(prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            return {
                                ...msg,
                                isLoading: false,
                                isGeneratingImage: false,
                                isError: true,
                                content: `${fullReply}\n\n[Error: ${err?.message || 'unknown error'}]`
                            };
                        }
                        return msg;
                    }));
                    abortControllerRef.current = null;
                    setIsLoading(false);
                }
            });
        } catch (e) {
            if (activeChatRequestIdRef.current !== chatRequestId) {
                return;
            }
            if (e.name !== 'AbortError') {
                abortControllerRef.current = null;
                setIsLoading(false);
            }
        }
    }, [
        addGuestSession,
        buildHistoryForAPI,
        history,
        isReadOnly,
        registerSessionSlug,
        sessionIdToSlug,
        storeGuestSessionToken,
        syncBrowserPath,
        syncPersistedCurrentSession,
        syncSessionIdentity,
        updateSessionIdentity
    ]);

    const stopGeneration = useCallback(() => {
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
            setIsLoading(false);
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

        sessionLoadRequestIdRef.current += 1;

        const chatRequestId = activeChatRequestIdRef.current + 1;
        activeChatRequestIdRef.current = chatRequestId;

        if (abortControllerRef.current) abortControllerRef.current.abort();
        abortControllerRef.current = new AbortController();

        setIsLoading(true);
        setHistory(prev => prev.map(msg => {
            if (msg.id === aiMessageId) {
                return { ...msg, isLoading: true, isError: false };
            }
            return msg;
        }));
        setHistory(prev => prev.slice(0, aiIndex + 1));

        const formData = new FormData();
        formData.append('message', userMessage.content);
        formData.append('model', model);
        formData.append('session_id', currentSessionIdRef.current || generateSessionId());
        formData.append('history', JSON.stringify(historyBefore));
        if (activeMindIdRef.current) {
            formData.append('mind_id', activeMindIdRef.current);
        }

        let fullReply = '';

        try {
            await apiService.chat(formData, abortControllerRef.current.signal, {
                onPart: (data) => {
                    if (activeChatRequestIdRef.current !== chatRequestId || !data?.reply_part) {
                        return;
                    }
                    fullReply += data.reply_part;
                    setHistory(prev => prev.map(msg => {
                        if (msg.id === aiMessageId) {
                            return { ...msg, content: fullReply, isLoading: true };
                        }
                        return msg;
                    }));
                },
                onWidgetUpdate: (widgetData) => {
                    if (activeChatRequestIdRef.current !== chatRequestId || !widgetData?.tag) {
                        return;
                    }
                    setHistory(prev => prev.map(msg => {
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
                onComplete: (finalData) => {
                    if (activeChatRequestIdRef.current !== chatRequestId) {
                        return;
                    }
                    setHistory(prev => prev.map(msg => {
                        if (msg.id === aiMessageId) {
                            const newVariant = {
                                content: finalData.reply || fullReply,
                                images: finalData.images || [],
                                sources: finalData.sources || [],
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
                                thinkingTime: newVariant.thinkingTime,
                                variants: newVariants,
                                currentVariantIndex: newCurrentIndex
                            };
                        }
                        return msg;
                    }));
                    abortControllerRef.current = null;
                    setIsLoading(false);
                },
                onError: (err) => {
                    if (activeChatRequestIdRef.current !== chatRequestId) {
                        return;
                    }
                    setHistory(prev => prev.map(msg => {
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
                    abortControllerRef.current = null;
                    setIsLoading(false);
                }
            });
        } catch (e) {
            if (activeChatRequestIdRef.current !== chatRequestId) {
                return;
            }
            if (e.name !== 'AbortError') {
                abortControllerRef.current = null;
                setIsLoading(false);
            }
        }
    }, [history, isLoading, buildHistoryForAPI]);
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

        sessionLoadRequestIdRef.current += 1;

        const chatRequestId = activeChatRequestIdRef.current + 1;
        activeChatRequestIdRef.current = chatRequestId;

        if (abortControllerRef.current) abortControllerRef.current.abort();
        abortControllerRef.current = new AbortController();

        setIsLoading(true);
        setHistory(prev => prev.map(msg => {
            if (msg.id === userMessageId) {
                return { ...msg, content: newText };
            }
            return msg;
        }));
        setHistory(prev => {
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

        setHistory(prev => [...prev, aiMsg]);

        const historyBefore = buildHistoryForAPI(userIndex);
        const formData = new FormData();
        formData.append('message', newText);
        formData.append('model', model);
        formData.append('session_id', currentSessionIdRef.current || generateSessionId());
        formData.append('history', JSON.stringify(historyBefore));
        if (activeMindIdRef.current) {
            formData.append('mind_id', activeMindIdRef.current);
        }

        let fullReply = '';

        try {
            await apiService.chat(formData, abortControllerRef.current.signal, {
                onPart: (data) => {
                    if (activeChatRequestIdRef.current !== chatRequestId || !data?.reply_part) {
                        return;
                    }
                    fullReply += data.reply_part;
                    setHistory(prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            return { ...msg, content: fullReply, isLoading: true };
                        }
                        return msg;
                    }));
                },
                onWidgetUpdate: (widgetData) => {
                    if (activeChatRequestIdRef.current !== chatRequestId || !widgetData?.tag) {
                        return;
                    }
                    setHistory(prev => prev.map(msg => {
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
                onComplete: (finalData) => {
                    if (activeChatRequestIdRef.current !== chatRequestId) {
                        return;
                    }
                    setHistory(prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            return {
                                ...msg,
                                isLoading: false,
                                content: finalData.reply || fullReply,
                                images: finalData.images || [],
                                sources: finalData.sources || []
                            };
                        }
                        return msg;
                    }));
                    abortControllerRef.current = null;
                    setIsLoading(false);
                },
                onError: (err) => {
                    if (activeChatRequestIdRef.current !== chatRequestId) {
                        return;
                    }
                    setHistory(prev => prev.map(msg => {
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
                    abortControllerRef.current = null;
                    setIsLoading(false);
                }
            });
        } catch (e) {
            if (activeChatRequestIdRef.current !== chatRequestId) {
                return;
            }
            if (e.name !== 'AbortError') {
                abortControllerRef.current = null;
                setIsLoading(false);
            }
        }
    }, [history, isLoading, buildHistoryForAPI, isReadOnly]);

    const enableSharing = useCallback(async () => {
        const sessionId = currentSessionIdRef.current;
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
        isLoading,
        currentSessionId,
        currentSessionSlug,
        sessionAccess,
        isReadOnly,
        loadSession,
        clearChat,
        setActiveSessionMindId,
        sendMessage,
        stopGeneration,
        regenerateMessage,
        editMessage,
        switchVariant,
        enableSharing,
        disableSharing,
        buildHistoryForAPI,
        messageVariants: messageVariantsRef.current
    };
};
