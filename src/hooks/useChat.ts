import { useState, useRef, useCallback, useEffect } from 'react';
import { apiService } from '../services/api';
import { ALLOW_GUEST_CHATS_SAVE } from '../utils/constants';
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

export const useChat = () => {
    const [history, setHistory] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [currentSessionId, setCurrentSessionId] = useState(null);
    const [currentSessionSlug, setCurrentSessionSlug] = useState(null);
    const [sessionAccess, setSessionAccess] = useState({
        isPublic: false,
        isOwner: false,
        publicId: null,
        shareUrl: null,
        readOnly: false
    });
    const [isReadOnly, setIsReadOnly] = useState(false);
    const abortControllerRef = useRef(null);
    const messageVariantsRef = useRef(new Map()); // Для хранения вариантов сообщений
    const slugIndexCacheRef = useRef({});

    const SLUG_INDEX_KEY = 'session_slug_index';
    const SESSION_ID_KEY = 'session_id';
    const SESSION_SLUG_KEY = 'session_slug';
    const GUEST_SESSIONS_KEY = 'guest_chat_history_ids';
    const GUEST_SESSION_TOKENS_KEY = 'guest_chat_tokens';
    const loadSlugIndex = useCallback(async () => {
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
    const sessionIdToSlug = useCallback((sessionId) => {
        const knownSlug = Object.keys(slugIndexCacheRef.current).find(
            slug => slugIndexCacheRef.current[slug] === sessionId
        );
        if (knownSlug) return knownSlug;
        return slugify(sessionId);
    }, []);
    const slugToSessionId = useCallback((slug) => {
        const indexed = slugIndexCacheRef.current[slug];
        if (indexed) return indexed;
        return slug;
    }, []);
    const addGuestSession = useCallback((sessionId) => {
        if (!ALLOW_GUEST_CHATS_SAVE || !sessionId) return;
        try {
            const raw = localStorage.getItem(GUEST_SESSIONS_KEY);
            let list = raw ? JSON.parse(raw) : [];
            list = list.filter(id => id !== sessionId);
            list.unshift(sessionId);
            if (list.length > 50) list.length = 50;
            localStorage.setItem(GUEST_SESSIONS_KEY, JSON.stringify(list));
        } catch (e) {
            console.warn("Guest session storage error", e);
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
            console.warn("Guest session token storage error", e);
        }
    }, []);
    useEffect(() => {
        loadSlugIndex();
    }, [loadSlugIndex]);
    const loadSession = useCallback(async (sessionIdOrSlug) => {
        setIsLoading(true);
        try {
            const sessionId = slugToSessionId(sessionIdOrSlug);
            const data = await apiService.getSessionHistory(sessionId);
            if (data && data.history) {
                const normalized = data.history.map(msg => {
                    const parts = msg.parts || [];
                    let text = parts.find(p => p.text)?.text || '';
                    if (text.trim().startsWith('{') && text.trim().endsWith('}')) {
                        try {
                            const parsed = JSON.parse(text);
                            if (parsed.url_path || parsed.original_name || parsed.mime_type) {
                                text = ''; // Удаляем из текста
                            }
                        } catch {
                        }
                    }
                    text = text.replace(/---\s*File:\s*[^-\n]+---[\s\S]*?---\s*End\s*File\s*---/gi, '');
                    text = text.replace(/\[Binary\s+file:[^\]]+\]/gi, '');

                    const images = parts.filter(p => p.image).map(p => p.image.url_path || p.image) || [];
                    const files = parts.filter(p => p.file).map(p => ({
                        file: {
                            url_path: p.file.url_path || p.file,
                            original_name: p.file.original_name || p.file.name || 'file',
                            mime_type: p.file.mime_type || 'application/octet-stream',
                            size: p.file.size || 0
                        }
                    })) || [];

                    return {
                        id: msg.id || Math.random().toString(36).substr(2, 9),
                        role: msg.role,
                        content: text.trim(),
                        images,
                        files,
                        timestamp: msg.timestamp,
                        parts: parts // Сохраняем полные parts для вариантов
                    };
                });
                setHistory(normalized);
                const resolvedSessionId = data.session_id || sessionId;

                const accessState = {
                    isPublic: !!data.is_public,
                    isOwner: !!data.is_owner,
                    publicId: data.public_id || null,
                    shareUrl: data.share_url || (data.public_id ? `${window.location.origin}/c/${data.public_id}` : null),
                    readOnly: !!(data.read_only || (data.is_public && !data.is_owner))
                };

                setSessionAccess(accessState);
                setIsReadOnly(accessState.readOnly);

                setCurrentSessionId(resolvedSessionId);
                const slug = data.public_id || sessionIdToSlug(resolvedSessionId);
                setCurrentSessionSlug(slug);
                registerSessionSlug(resolvedSessionId, slug);
                const path = window.location.pathname;
                if (!path.startsWith(`/c/${encodeURIComponent(slug)}`)) {
                    window.history.replaceState({}, '', `/c/${encodeURIComponent(slug)}`);
                }
                if (ALLOW_GUEST_CHATS_SAVE) {
                    localStorage.setItem(SESSION_ID_KEY, sessionId);
                    localStorage.setItem(SESSION_SLUG_KEY, slug);
                    addGuestSession(sessionId);
                }
            } else {
                setHistory([]);
                setSessionAccess({
                    isPublic: false,
                    isOwner: false,
                    publicId: null,
                    shareUrl: null,
                    readOnly: false
                });
                setIsReadOnly(false);
            }
        } catch (e) {
            console.error("Failed to load session", e);
            setHistory([]);
            setSessionAccess({
                isPublic: false,
                isOwner: false,
                publicId: null,
                shareUrl: null,
                readOnly: false
            });
            setIsReadOnly(false);
        } finally {
            setIsLoading(false);
        }
    }, [slugToSessionId, sessionIdToSlug, addGuestSession]);
    const clearChat = useCallback(() => {
        setHistory([]);
        setCurrentSessionId(null);
        setCurrentSessionSlug(null);
        setSessionAccess({
            isPublic: false,
            isOwner: false,
            publicId: null,
            shareUrl: null,
            readOnly: false
        });
        setIsReadOnly(false);
        messageVariantsRef.current.clear();
        if (window.location.pathname !== '/') {
            window.history.pushState({}, '', '/');
        }
        if (!ALLOW_GUEST_CHATS_SAVE) return;
        try {
            const newSessionId = generateSessionId();
            localStorage.setItem(SESSION_ID_KEY, newSessionId);
            addGuestSession(newSessionId);
        } catch (error) {
            console.warn('Failed to create new guest session', error);
        }
    }, [addGuestSession]);
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
    const sendMessage = useCallback(async (text, files = [], model = 'gemini', options = {}) => {
        const { webSearch = false, censorship = false, ...metadata } = options;
        if (!text.trim() && files.length === 0) return;
        if (isReadOnly) {
            console.warn('Attempt to send message in read-only chat is blocked.');
            return;
        }

        setIsLoading(true);
        let sessionId = currentSessionId;
        const path = window.location.pathname;
        const isNewChat = path === '/' || !path.startsWith('/c/');

        if (!sessionId || isNewChat) {
            sessionId = generateSessionId();
            const slug = sessionIdToSlug(sessionId);
            setCurrentSessionId(sessionId);
            setCurrentSessionSlug(slug);
            registerSessionSlug(sessionId, slug);

            if (ALLOW_GUEST_CHATS_SAVE) {
                localStorage.setItem(SESSION_ID_KEY, sessionId);
                localStorage.setItem(SESSION_SLUG_KEY, slug);
                addGuestSession(sessionId);
            }
            if (isNewChat) {
                window.history.pushState({}, '', `/c/${encodeURIComponent(slug)}`);
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
        if (abortControllerRef.current) abortControllerRef.current.abort();
        abortControllerRef.current = new AbortController();

        const formData = new FormData();
        formData.append('message', text);
        formData.append('model', model);
        formData.append('user_id', sessionId);
        formData.append('history', JSON.stringify(buildHistoryForAPI(history.length)));
        formData.append('webSearch', String(webSearch));
        formData.append('censorship', String(censorship));
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
                    if (!data) return;
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

                    if (firstChunk) {
                        setHistory(prev => prev.map(msg => {
                            if (msg.id === aiMsgId) {
                                return { ...msg, isGeneratingImage: false };
                            }
                            return msg;
                        }));
                        firstChunk = false;
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
                    if (widgetData?.tag) {
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
                    }
                },
                onComplete: (finalData) => {
                    if (finalData?.aborted) {
                        fullReply += '\n\n_[Генерация остановлена]_';
                    }

                    if (finalData?.sessionId && finalData.sessionId !== sessionId) {
                        const newSessionId = finalData.sessionId;
                        const slug = finalData.sessionSlug || sessionIdToSlug(newSessionId);
                        setCurrentSessionId(newSessionId);
                        setCurrentSessionSlug(slug);
                        registerSessionSlug(newSessionId, slug);

                        if (ALLOW_GUEST_CHATS_SAVE) {
                            localStorage.setItem(SESSION_ID_KEY, newSessionId);
                            localStorage.setItem(SESSION_SLUG_KEY, slug);
                            addGuestSession(newSessionId);
                        }
                        window.history.pushState({}, '', `/c/${encodeURIComponent(slug)}`);
                    }

                    if (finalData?.session_token) {
                        const tokenSessionId = finalData.sessionId || sessionId;
                        storeGuestSessionToken(tokenSessionId, finalData.session_token);
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
                                content: finalContent, // Для обратной совместимости
                                images: finalData.images || [],
                                sources: finalData.sources || [],
                                thinkingTime: finalData.thinkingTime,
                                variants: [firstVariant],
                                currentVariantIndex: 0
                            };
                        }
                        return msg;
                    }));
                    setIsLoading(false);
                },
                onError: (err) => {
                    console.error("Chat error", err);
                    setHistory(prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            return {
                                ...msg,
                                isLoading: false,
                                isError: true,
                                content: fullReply + `\n\n[Ошибка: ${err?.message || 'неизвестная ошибка'}]`
                            };
                        }
                        return msg;
                    }));
                    setIsLoading(false);
                }
            });
        } catch (e) {
            if (e.name !== 'AbortError') {
                setIsLoading(false);
            }
        }
    }, [currentSessionId, history, sessionIdToSlug, registerSessionSlug, addGuestSession, buildHistoryForAPI]);

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

        setIsLoading(true);
        setHistory(prev => prev.map(msg => {
            if (msg.id === aiMessageId) {
                return { ...msg, isLoading: true, isError: false };
            }
            return msg;
        }));
        setHistory(prev => prev.slice(0, aiIndex + 1));

        if (abortControllerRef.current) abortControllerRef.current.abort();
        abortControllerRef.current = new AbortController();

        const formData = new FormData();
        formData.append('message', userMessage.content);
        formData.append('model', model);
        formData.append('user_id', currentSessionId || generateSessionId());
        formData.append('history', JSON.stringify(historyBefore));

        let fullReply = '';

        try {
            await apiService.chat(formData, abortControllerRef.current.signal, {
                onPart: (data) => {
                    if (data.reply_part) {
                        fullReply += data.reply_part;
                        setHistory(prev => prev.map(msg => {
                            if (msg.id === aiMessageId) {
                                return { ...msg, content: fullReply, isLoading: true };
                            }
                            return msg;
                        }));
                    }
                },
                onWidgetUpdate: (widgetData) => {
                    if (widgetData?.tag) {
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
                    }
                },
                onComplete: (finalData) => {
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
                                content: newVariant.content, // Для обратной совместимости
                                images: newVariant.images,
                                sources: newVariant.sources,
                                thinkingTime: newVariant.thinkingTime,
                                variants: newVariants,
                                currentVariantIndex: newCurrentIndex
                            };
                        }
                        return msg;
                    }));
                    setIsLoading(false);
                },
                onError: (err) => {
                    setHistory(prev => prev.map(msg => {
                        if (msg.id === aiMessageId) {
                            return {
                                ...msg,
                                isLoading: false,
                                isError: true,
                                content: fullReply + `\n\n[Ошибка: ${err?.message || 'неизвестная ошибка'}]`
                            };
                        }
                        return msg;
                    }));
                    setIsLoading(false);
                }
            });
        } catch (e) {
            if (e.name !== 'AbortError') {
                setIsLoading(false);
            }
        }
    }, [history, isLoading, currentSessionId, buildHistoryForAPI, isReadOnly]);
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

        if (abortControllerRef.current) abortControllerRef.current.abort();
        abortControllerRef.current = new AbortController();

        const historyBefore = buildHistoryForAPI(userIndex);
        const formData = new FormData();
        formData.append('message', newText);
        formData.append('model', model);
        formData.append('user_id', currentSessionId || generateSessionId());
        formData.append('history', JSON.stringify(historyBefore));

        let fullReply = '';

        try {
            await apiService.chat(formData, abortControllerRef.current.signal, {
                onPart: (data) => {
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
                    if (widgetData?.tag) {
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
                    }
                },
                onComplete: (finalData) => {
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
                    setIsLoading(false);
                },
                onError: (err) => {
                    setHistory(prev => prev.map(msg => {
                        if (msg.id === aiMsgId) {
                            return {
                                ...msg,
                                isLoading: false,
                                isError: true,
                                content: fullReply + `\n\n[Ошибка: ${err?.message || 'неизвестная ошибка'}]`
                            };
                        }
                        return msg;
                    }));
                    setIsLoading(false);
                }
            });
        } catch (e) {
            if (e.name !== 'AbortError') {
                setIsLoading(false);
            }
        }
    }, [history, isLoading, currentSessionId, buildHistoryForAPI, isReadOnly]);

    const enableSharing = useCallback(async () => {
        if (!currentSessionId) return null;
        const data = await apiService.toggleShare(currentSessionId, true);
        const accessState = {
            isPublic: !!data?.is_public,
            isOwner: true,
            publicId: data?.public_id || null,
            shareUrl: data?.share_url || (data?.public_id ? `${window.location.origin}/c/${data.public_id}` : null),
            readOnly: false
        };
        setSessionAccess(accessState);
        setIsReadOnly(accessState.readOnly);
        if (data?.session_id) {
            setCurrentSessionId(data.session_id);
        }
        return data;
    }, [currentSessionId]);

    const disableSharing = useCallback(async () => {
        if (!currentSessionId) return null;
        const data = await apiService.toggleShare(currentSessionId, false);
        const accessState = {
            isPublic: false,
            isOwner: true,
            publicId: data?.public_id || null,
            shareUrl: null,
            readOnly: false
        };
        setSessionAccess(accessState);
        setIsReadOnly(false);
        if (data?.session_id) {
            setCurrentSessionId(data.session_id);
        }
        return data;
    }, [currentSessionId]);

    return {
        history,
        isLoading,
        currentSessionId,
        currentSessionSlug,
        sessionAccess,
        isReadOnly,
        loadSession,
        clearChat,
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
