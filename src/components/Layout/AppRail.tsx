import React, { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { apiService } from '../../services/api';
import { authService } from '../../services/auth';
import { useAuth } from '../../context/AuthContext';
import { useSettings } from '../../context/SettingsContext';
import { ALLOW_GUEST_CHATS_SAVE } from '../../utils/constants';

const normalizeText = (value) => {
    if (!value) return '';
    return value
        .toLowerCase()
        .normalize('NFKD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/\s+/g, ' ')
        .trim();
};

const splitTokens = (value) => {
    if (!value) return [];
    return value.split(/[^a-z0-9а-яё]+/i).filter(Boolean);
};

const isSubsequence = (query, text) => {
    let qIndex = 0;
    for (let i = 0; i < text.length && qIndex < query.length; i += 1) {
        if (text[i] === query[qIndex]) {
            qIndex += 1;
        }
    }
    return qIndex === query.length;
};

const scoreMatch = (query, text) => {
    const normalizedQuery = normalizeText(query);
    const normalizedText = normalizeText(text);
    if (!normalizedQuery || !normalizedText) return 0;

    let score = 0;
    const index = normalizedText.indexOf(normalizedQuery);
    if (index !== -1) {
        score += 80;
        score += Math.max(0, 20 - index);
    }

    const queryTokens = splitTokens(normalizedQuery);
    const textTokens = splitTokens(normalizedText);

    if (queryTokens.length > 0 && textTokens.length > 0) {
        let matchedTokens = 0;
        let exactHits = 0;

        queryTokens.forEach((queryToken) => {
            for (const token of textTokens) {
                if (token === queryToken) {
                    matchedTokens += 1;
                    exactHits += 1;
                    score += 16;
                    return;
                }
                if (token.startsWith(queryToken)) {
                    matchedTokens += 1;
                    score += 10;
                    return;
                }
                if (token.includes(queryToken)) {
                    matchedTokens += 1;
                    score += 6;
                    return;
                }
            }
        });

        if (matchedTokens === queryTokens.length) {
            score += 12;
        }

        score += Math.min(10, exactHits * 2);
    }

    if (normalizedQuery.length >= 3 && isSubsequence(normalizedQuery, normalizedText)) {
        score += 6;
    }

    return score;
};

const AppRail = ({ isExpanded, onToggle, sessions, onNewChat, onSelectSession, onSettingsClick, onSessionDeleted, onSessionRenamed }) => {
    const { t } = useTranslation();
    const { isAuthenticated } = useAuth();
    const { settings } = useSettings();
    const [favorites, setFavorites] = useState([]);
    const [openMenuId, setOpenMenuId] = useState(null);
    const [editingSessionId, setEditingSessionId] = useState(null);
    const [editingTitle, setEditingTitle] = useState('');
    const [localSessions, setLocalSessions] = useState(sessions);
    const [searchOpen, setSearchOpen] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [searchHintActive, setSearchHintActive] = useState(false);
    useEffect(() => {
        const loadFavorites = async () => {
            if (isAuthenticated) {
                try {
                    const dbFavorites = await authService.getFavorites();
                    setFavorites(dbFavorites);
                } catch (error) {
                    console.warn('Failed to load favorites from DB, using localStorage:', error);
                    try {
                        const localFavorites = JSON.parse(localStorage.getItem('favoriteChats') || '[]');
                        setFavorites(localFavorites);
                    } catch {
                        setFavorites([]);
                    }
                }
            } else {
                try {
                    const localFavorites = JSON.parse(localStorage.getItem('favoriteChats') || '[]');
                    setFavorites(localFavorites);
                } catch {
                    setFavorites([]);
                }
            }
        };
        loadFavorites();
    }, [isAuthenticated]);
    useEffect(() => {
        setLocalSessions(sessions);
    }, [sessions]);
    useEffect(() => {
        const handleClickOutside = (e) => {
            if (!e.target.closest('.chat-menu-wrapper')) {
                setOpenMenuId(null);
            }
        };

        if (openMenuId) {
            document.addEventListener('click', handleClickOutside);
            return () => document.removeEventListener('click', handleClickOutside);
        }
    }, [openMenuId]);

    const toggleFavorite = async (sessionId, e) => {
        e.stopPropagation();
        const isFavorite = favorites.includes(sessionId);

        if (isAuthenticated) {
            try {
                if (isFavorite) {
                    const result = await authService.removeFavorite(sessionId);
                    if (result.success) {
                        setFavorites(result.favorites || []);
                    } else {
                        const newFavorites = favorites.filter(id => id !== sessionId);
                        setFavorites(newFavorites);
                        localStorage.setItem('favoriteChats', JSON.stringify(newFavorites));
                    }
                } else {
                    const result = await authService.addFavorite(sessionId);
                    if (result.success) {
                        setFavorites(result.favorites || []);
                    } else {
                        const newFavorites = [...favorites, sessionId];
                        setFavorites(newFavorites);
                        localStorage.setItem('favoriteChats', JSON.stringify(newFavorites));
                    }
                }
            } catch (error) {
                console.error('Failed to update favorite in DB:', error);
                const newFavorites = isFavorite
                    ? favorites.filter(id => id !== sessionId)
                    : [...favorites, sessionId];
                setFavorites(newFavorites);
                localStorage.setItem('favoriteChats', JSON.stringify(newFavorites));
            }
        } else {
            const newFavorites = isFavorite
                ? favorites.filter(id => id !== sessionId)
                : [...favorites, sessionId];
            setFavorites(newFavorites);
            localStorage.setItem('favoriteChats', JSON.stringify(newFavorites));
        }
    };

    const handleDelete = async (sessionId, e) => {
        e.stopPropagation();
        try {
            await apiService.deleteSession(sessionId);
            if (onSessionDeleted) {
                onSessionDeleted(sessionId);
            }
            if (ALLOW_GUEST_CHATS_SAVE) {
                try {
                    const raw = localStorage.getItem('guest_chat_history_ids');
                    let list = raw ? JSON.parse(raw) : [];
                    list = list.filter(id => id !== sessionId);
                    localStorage.setItem('guest_chat_history_ids', JSON.stringify(list));
                } catch (e) {
                    console.warn('Failed to update guest sessions list', e);
                }
            }
        } catch (error) {
            console.error('Failed to delete session:', error);
        }
    };

    const handleRename = (sessionId, e) => {
        e.stopPropagation();
        const session = localSessions.find(s => s.session_id === sessionId);
        const currentTitle = session?.title || (sessionId || '').slice(0, 16) || t('rail.untitled');

        setEditingSessionId(sessionId);
        setEditingTitle(currentTitle);
        setOpenMenuId(null); // Закрываем меню
    };

    const handleSaveRename = async (sessionId) => {
        const newTitle = editingTitle.trim();
        const session = localSessions.find(s => s.session_id === sessionId);
        const currentTitle = session?.title || (sessionId || '').slice(0, 16) || t('rail.untitled');

        if (!newTitle) {
            setEditingSessionId(null);
            return;
        }

        if (newTitle === currentTitle) {
            setEditingSessionId(null);
            return;
        }

        try {
            const result = await apiService.renameSession(sessionId, newTitle);
            if (result && result.title) {
                setLocalSessions(prevSessions =>
                    prevSessions.map(s =>
                        s.session_id === sessionId
                            ? { ...s, title: result.title }
                            : s
                    )
                );
                if (onSessionRenamed) {
                    onSessionRenamed(sessionId, result.title);
                }
                console.log('Session renamed successfully:', result.title);
            }
        } catch (error) {
            console.error('Failed to rename session:', error);
        } finally {
            setEditingSessionId(null);
        }
    };

    const handleCancelRename = () => {
        setEditingSessionId(null);
        setEditingTitle('');
    };

    const handleShare = async (sessionId, e) => {
        e.stopPropagation();
        try {
            console.log('Share session:', sessionId);
        } catch (error) {
            console.error('Failed to share session:', error);
        }
    };
    const sortedSessions = [...localSessions].sort((a, b) => {
        const aIsFavorite = favorites.includes(a.session_id);
        const bIsFavorite = favorites.includes(b.session_id);
        if (aIsFavorite && !bIsFavorite) return -1;
        if (!aIsFavorite && bIsFavorite) return 1;
        return 0;
    });

    const searchHint = t('rail.searchHint');
    const effectiveQuery = searchHintActive ? '' : searchQuery.trim();

    const filteredSessions = useMemo(() => {
        if (!effectiveQuery) return sortedSessions;

        const scored = sortedSessions
            .map((session, index) => {
                const preview = (session.last_message && session.last_message.trim()) ? session.last_message.trim() : '';
                const title = (session.title && session.title.trim()) || preview || (session.session_id || '').slice(0, 16) || t('rail.untitled');
                const score = scoreMatch(effectiveQuery, `${title} ${preview}`);
                return { session, score, index };
            })
            .filter(item => item.score > 0)
            .sort((a, b) => (b.score - a.score) || (a.index - b.index));

        return scored.map(item => item.session);
    }, [effectiveQuery, sortedSessions, t]);

    const handleSearchToggle = () => {
        if (!isExpanded && onToggle) {
            onToggle();
        }
        setSearchOpen((prev) => {
            const next = !prev;
            if (!next) {
                setSearchQuery('');
                setSearchHintActive(false);
                return next;
            }
            if (!searchQuery) {
                setSearchQuery(searchHint);
                setSearchHintActive(true);
            }
            return next;
        });
    };

    return (
        <nav className={`app-rail ${isExpanded ? 'expanded' : ''}`} id="appRail">
            <div className="rail-toggle-zone">
                <button
                    className="rail-toggle-btn"
                    id="railToggleBtn"
                    onClick={onToggle}
                    title={isExpanded ? t('rail.collapse') : t('rail.expand')}
                >
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }}>
                        <path d="M9 18l6-6-6-6" />
                    </svg>
                </button>
            </div>

            <div className="rail-quick-actions">
                <button className="rail-icon-btn" id="railNewChat" onClick={onNewChat}>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 5v14M5 12h14" />
                    </svg>
                    <span>{t('rail.newChat')}</span>
                </button>
                <button
                    className={`rail-icon-btn ${searchOpen ? 'active' : ''}`}
                    id="railChatSearch"
                    onClick={handleSearchToggle}
                    title={t('rail.searchChats')}
                    aria-label={t('rail.searchChats')}
                >
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="11" cy="11" r="7" />
                        <line x1="21" y1="21" x2="16.65" y2="16.65" />
                    </svg>
                    <span>{t('rail.searchChats')}</span>
                </button>
            </div>

            {searchOpen && isExpanded && (
                <div className="rail-search-container">
                    <input
                        type="text"
                        className={`rail-search-input ${searchHintActive ? 'is-hint' : ''}`}
                        value={searchQuery}
                        onChange={(e) => {
                            setSearchHintActive(false);
                            setSearchQuery(e.target.value);
                        }}
                        onFocus={() => {
                            if (searchHintActive) {
                                setSearchQuery('');
                                setSearchHintActive(false);
                            }
                        }}
                        onBlur={() => {
                            if (!searchQuery.trim()) {
                                setSearchQuery(searchHint);
                                setSearchHintActive(true);
                            }
                        }}
                        placeholder={t('rail.searchPlaceholder')}
                        aria-label={t('rail.searchInput')}
                    />
                </div>
            )}

            <div className="rail-divider">
                <span>{t('rail.yourChats')}</span>
            </div>

            <div className="rail-content-wrapper rail-chat-container">
                <ul id="chatHistoryList" className="rail-chat-list">
                    {filteredSessions.map(session => {
                        const isFavorite = favorites.includes(session.session_id);
                        const preview = (session.last_message && session.last_message.trim()) ? session.last_message.trim() : '';
                        const title = (session.title && session.title.trim()) || preview || (session.session_id || '').slice(0, 16) || t('rail.untitled');
                        const showPreview = !!settings.showChatPreview && !!preview && preview !== title;

                        return (
                            <li
                                key={session.session_id}
                                className={`chat-history-item ${isFavorite ? 'favorite' : ''}`}
                                title={title}
                                onClick={() => onSelectSession(session.session_id)}
                            >
                                <div className="chat-item-main">
                                    <div className="chat-item-title-row">
                                        <span className="chat-item-title">
                                            {editingSessionId === session.session_id ? (
                                                <input
                                                    type="text"
                                                    value={editingTitle}
                                                    onChange={(e) => setEditingTitle(e.target.value)}
                                                    onKeyDown={(e) => {
                                                        if (e.key === 'Enter') {
                                                            handleSaveRename(session.session_id);
                                                        } else if (e.key === 'Escape') {
                                                            handleCancelRename();
                                                        }
                                                    }}
                                                    onBlur={() => handleSaveRename(session.session_id)}
                                                    onClick={(e) => e.stopPropagation()}
                                                    autoFocus
                                                    className="chat-rename-input"
                                                    maxLength={200}
                                                />
                                            ) : (
                                                title
                                            )}
                                        </span>
                                        {session.is_public && (
                                            <span className="chat-public-chip" title={t('rail.publicChat')}>
                                                <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                                                    <circle cx="12" cy="12" r="10" stroke="currentColor" fill="none" strokeWidth="1.6"/>
                                                    <path d="M2 12h20M12 2c3.5 3.2 3.5 16.8 0 20M7.5 4.5c2.2 2.2 2.2 13 0 15.2M16.5 4.5c-2.2 2.2-2.2 13 0 15.2" stroke="currentColor" fill="none" strokeWidth="1.4"/>
                                                </svg>
                                                {t('rail.public')}
                                            </span>
                                        )}
                                    </div>
                                    {showPreview && editingSessionId !== session.session_id && (
                                        <div className="chat-item-preview">{preview}</div>
                                    )}
                                </div>
                                <span className="chat-item-details">
                                    {}
                                    <div className="chat-item-actions">
                                        <div className="chat-menu-wrapper">
                                            <button
                                                className="chat-menu-btn"
                                                title={t('rail.menu')}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    setOpenMenuId(openMenuId === session.session_id ? null : session.session_id);
                                                }}
                                            >
                                                <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                                                    <circle cx="12" cy="5" r="2"/>
                                                    <circle cx="12" cy="12" r="2"/>
                                                    <circle cx="12" cy="19" r="2"/>
                                                </svg>
                                            </button>
                                            {openMenuId === session.session_id && (
                                                <div className="chat-dropdown-menu">
                                                    <button
                                                        className="menu-item favorite-menu-item"
                                                        onClick={(e) => {
                                                            toggleFavorite(session.session_id, e);
                                                            setOpenMenuId(null);
                                                        }}
                                                    >
                                                        <svg viewBox="0 0 24 24" width="16" height="16">
                                                            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
                                                        </svg>
                                                        <span>{isFavorite ? t('rail.favorite.remove') : t('rail.favorite.add')}</span>
                                                    </button>
                                                    <button
                                                        className="menu-item"
                                                        onClick={(e) => {
                                                            handleShare(session.session_id, e);
                                                            setOpenMenuId(null);
                                                        }}
                                                    >
                                                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
                                                            <circle cx="18" cy="5" r="3"/>
                                                            <circle cx="6" cy="12" r="3"/>
                                                            <circle cx="18" cy="19" r="3"/>
                                                            <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/>
                                                            <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
                                                        </svg>
                                                        <span>{t('rail.share')}</span>
                                                    </button>
                                                    <button
                                                        className="menu-item"
                                                        onClick={(e) => {
                                                            handleRename(session.session_id, e);
                                                            setOpenMenuId(null);
                                                        }}
                                                    >
                                                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
                                                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                                                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                                                        </svg>
                                                        <span>{t('rail.rename')}</span>
                                                    </button>
                                                    <button
                                                        className="menu-item delete-menu-item"
                                                        onClick={(e) => {
                                                            handleDelete(session.session_id, e);
                                                            setOpenMenuId(null);
                                                        }}
                                                    >
                                                        <svg viewBox="0 0 24 24" width="16" height="16">
                                                            <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                                                        </svg>
                                                        <span>{t('rail.delete')}</span>
                                                    </button>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </span>
                            </li>
                        );
                    })}

                    {filteredSessions.length === 0 && (
                        <li className="empty-history-message">
                            {effectiveQuery ? t('rail.noResults') : t('rail.emptyHistory')}
                        </li>
                    )}
                </ul>
            </div>

            <div className="rail-actions-bottom">
                <button className="rail-btn-secondary" id="railSettings" onClick={onSettingsClick}>
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="3" />
                        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                    </svg>
                    <span>{t('rail.settings')}</span>
                </button>
            </div>
        </nav>
    );
};

export default AppRail;
