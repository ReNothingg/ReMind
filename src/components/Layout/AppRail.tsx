import { useState, useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowRight, BookOpen, Check, ChevronRight, Ellipsis, EllipsisVertical, FolderOpen, ListFilter, MessageSquarePlus, Pencil, Settings2, ShieldCheck, SquarePen, Trash2, X } from 'lucide-react';
import { apiService } from '../../services/api';
import { authService } from '../../services/auth';
import { useAuth } from '../../context/AuthContext';
import { useSettings } from '../../context/SettingsContext';
import { removeGuestSession } from '../../features/sessions/guestSessionStorage';
import { cn } from '../../utils/cn';
import Pet, { type PetState } from '../UI/Pet';

function ProjectIcon({ add = false }: { add?: boolean }) {
  return (
    <svg
      aria-hidden="true"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3.5 7.7a2 2 0 0 1 2-2h4l2.1 2.2h6.8a2.1 2.1 0 0 1 2.1 2.1v6.4a2 2 0 0 1-2 2H5.5a2 2 0 0 1-2-2z" />
      {add && <path d="M12 11.1v4.1M10 13.1h4" />}
    </svg>
  );
}

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

const RailActionButton = ({
  active = false,
  children,
  className,
  expanded,
  label,
  title = undefined,
  'aria-label': ariaLabel = undefined,
  ...props
}) => (
  <button
    type="button"
    className={cn(
      'ui-rail-action-button',
      expanded ? 'ui-rail-action-button-expanded' : 'ui-rail-action-button-collapsed',
      active && 'ui-rail-action-button-active',
      className
    )}
    aria-label={ariaLabel || label}
    title={title || label}
    {...props}
  >
    {children}
    <span className={cn('ui-rail-action-label', expanded ? 'inline' : 'hidden')}>{label}</span>
  </button>
);

const RailMenuItem = ({ children, className = 'menu-item', danger = false, icon, ...props }) => (
  <button
    type="button"
    role="menuitem"
    className={cn('ui-rail-menu-item', danger && 'ui-rail-menu-item-danger', className)}
    {...props}
  >
    {icon}
    <span>{children}</span>
  </button>
);

const getMindInitials = (mind) => {
  const words = (mind?.name || 'M').split(/\s+/).filter(Boolean).slice(0, 2);
  return (
    words
      .map((word) => word[0])
      .join('')
      .toUpperCase() || 'M'
  );
};

const MindRailIcon = () => (
  <svg
    width="20"
    height="20"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M8.5 6.5a3 3 0 0 1 5.7-1.3A3.2 3.2 0 0 1 19 8a3.3 3.3 0 0 1-.7 6.5 4.2 4.2 0 0 1-7.8 2.6A3.7 3.7 0 0 1 5 13.7 3.9 3.9 0 0 1 8.5 6.5Z" />
    <path d="M9 10h6M10 14h4" />
  </svg>
);

const AppRail = ({
  activeMindId = null,
  currentPath = '/',
  currentSessionId,
  isExpanded,
  isMobile = false,
  onAdminClick,
  onAutomationsClick,
  onMindsClick,
  onPluginsClick,
  onOpenProject,
  onProjectSettings,
  onNewPersonalChat,
  onReferenceChat,
  activeProjectId,
  projectStore,
  onSessionMoved,
  onProjectsChanged,
  onNewChat,
  onSelectMind,
  onSelectSession,
  onSessionDeleted,
  onSessionRenamed,
  onCompactSession,
  onViewContext,
  onSettingsClick,
  onToggle,
  petState = 'idle' as PetState,
  pinnedMinds = [],
  sessionActivity = {},
  sessions,
}) => {
  const { t } = useTranslation();
  const { isAuthenticated, user } = useAuth();
  const { settings } = useSettings();
  const projectHeading = useRef<HTMLDivElement>(null);
  const [projectEditor, setProjectEditor] = useState<{ id?: string; name: string } | null>(null);
  const [projectExpansion, setProjectExpansion] = useState<ReadonlyMap<string, boolean>>(() => new Map());
  const [projectBusy, setProjectBusy] = useState(false);
  const [projectError, setProjectError] = useState(false);
  const projects = projectStore.projects;
  const projectIds = new Set(projects.map((project) => project.id));
  const changeProject = async (action: () => Promise<unknown>) => {
    if (projectBusy) return;
    setProjectBusy(true);
    setProjectError(false);
    try {
      await action();
    } catch {
      setProjectError(true);
    } finally {
      setProjectBusy(false);
    }
  };
  const [favorites, setFavorites] = useState([]);
  const [openMenuId, setOpenMenuId] = useState(null);
  const [editingSessionId, setEditingSessionId] = useState(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [localSessions, setLocalSessions] = useState(sessions);
  const [searchQuery, setSearchQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [isSourceFilterOpen, setIsSourceFilterOpen] = useState(false);
  const [arePinnedMindsExpanded, setArePinnedMindsExpanded] = useState(true);
  const menuTriggerRefs = useRef(new Map());
  const sourceFilterRef = useRef(null);

  useEffect(() => {
    if (isExpanded) {
      return;
    }

    setOpenMenuId(null);
    setEditingSessionId(null);
    setEditingTitle('');
    setSearchQuery('');
    setSourceFilter('all');
    setIsSourceFilterOpen(false);
  }, [isExpanded]);

  useEffect(() => {
    if (!isSourceFilterOpen) return undefined;
    const handlePointerDown = (event) => {
      if (!sourceFilterRef.current?.contains(event.target)) {
        setIsSourceFilterOpen(false);
      }
    };
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        setIsSourceFilterOpen(false);
      }
    };
    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isSourceFilterOpen]);

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
            const newFavorites = favorites.filter((id) => id !== sessionId);
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
          ? favorites.filter((id) => id !== sessionId)
          : [...favorites, sessionId];
        setFavorites(newFavorites);
        localStorage.setItem('favoriteChats', JSON.stringify(newFavorites));
      }
    } else {
      const newFavorites = isFavorite
        ? favorites.filter((id) => id !== sessionId)
        : [...favorites, sessionId];
      setFavorites(newFavorites);
      localStorage.setItem('favoriteChats', JSON.stringify(newFavorites));
    }
  };

  const handleDelete = async (sessionId, e) => {
    e.stopPropagation();
    try {
      await apiService.deleteSession(sessionId);
      setLocalSessions((prevSessions) =>
        prevSessions.filter((session) => session.session_id !== sessionId)
      );
      setFavorites((prevFavorites) => prevFavorites.filter((id) => id !== sessionId));
      if (editingSessionId === sessionId) {
        setEditingSessionId(null);
        setEditingTitle('');
      }
      if (onSessionDeleted) {
        onSessionDeleted(sessionId);
      }
      removeGuestSession(sessionId);
    } catch (error) {
      console.error('Failed to delete session:', error);
    }
  };

  const handleRename = (sessionId, e) => {
    e.stopPropagation();
    const session = localSessions.find((s) => s.session_id === sessionId);
    const currentTitle = session?.title || (sessionId || '').slice(0, 16) || t('rail.untitled');

    setEditingSessionId(sessionId);
    setEditingTitle(currentTitle);
    setOpenMenuId(null);
  };

  const handleSaveRename = async (sessionId) => {
    const newTitle = editingTitle.trim();
    const session = localSessions.find((s) => s.session_id === sessionId);
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
        setLocalSessions((prevSessions) =>
          prevSessions.map((s) => (s.session_id === sessionId ? { ...s, title: result.title } : s))
        );
        if (onSessionRenamed) {
          onSessionRenamed(sessionId, result.title);
        }
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

  const sortedSessions = [...localSessions].sort((a, b) => {
    const aIsFavorite = favorites.includes(a.session_id);
    const bIsFavorite = favorites.includes(b.session_id);
    if (aIsFavorite && !bIsFavorite) return -1;
    if (!aIsFavorite && bIsFavorite) return 1;
    return 0;
  });

  const effectiveQuery = searchQuery.trim();

  const filteredSessions = useMemo(() => {
    const sourceSessions = sortedSessions.filter((session) => {
      const source = session.source || 'web';
      if (sourceFilter === 'telegram') return source.startsWith('telegram_');
      if (sourceFilter === 'web') return source === 'web';
      return true;
    });
    if (!effectiveQuery) return sourceSessions;

    const scored = sourceSessions
      .map((session, index) => {
        const preview =
          session.last_message && session.last_message.trim() ? session.last_message.trim() : '';
        const title =
          (session.title && session.title.trim()) ||
          preview ||
          (session.session_id || '').slice(0, 16) ||
          t('rail.untitled');
        const score = scoreMatch(effectiveQuery, `${title} ${preview}`);
        return { session, score, index };
      })
      .filter((item) => item.score > 0)
      .sort((a, b) => b.score - a.score || a.index - b.index);

    return scored.map((item) => item.session);
  }, [effectiveQuery, sortedSessions, sourceFilter, t]);

  const getSourceLabel = (source) => {
    if (source === 'telegram_private') return t('rail.channelFilter.private');
    if (source === 'telegram_group') return t('rail.channelFilter.group');
    if (source === 'telegram_guest') return t('rail.channelFilter.guest');
    if (source === 'telegram_inline') return t('rail.channelFilter.inline');
    return '';
  };

  const getSessionActivityLabel = (activity) => {
    if (!activity?.status) return '';
    if (activity.status === 'generating') {
      return t('rail.statusGenerating');
    }
    if (activity.status === 'error') {
      return t('rail.statusError');
    }
    return t('rail.statusComplete');
  };

  const focusSessionMenuItem = (sessionId, edge = 'first') => {
    window.requestAnimationFrame(() => {
      const menu = document.getElementById(`rail-session-menu-${sessionId}`);
      const items = menu?.querySelectorAll('[role="menuitem"]');
      const target = edge === 'last' ? items?.[items.length - 1] : items?.[0];
      if (target instanceof HTMLElement) target.focus();
    });
  };

  const handleSessionMenuKeyDown = (event, sessionId) => {
    const items = Array.from(event.currentTarget.querySelectorAll('[role="menuitem"]'));
    const currentIndex = items.indexOf(document.activeElement);

    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      setOpenMenuId(null);
      window.requestAnimationFrame(() => menuTriggerRefs.current.get(sessionId)?.focus());
      return;
    }

    if (items.length === 0) return;

    let nextIndex = currentIndex;
    if (event.key === 'ArrowDown') {
      nextIndex = (currentIndex + 1) % items.length;
    } else if (event.key === 'ArrowUp') {
      nextIndex = (currentIndex - 1 + items.length) % items.length;
    } else if (event.key === 'Home') {
      nextIndex = 0;
    } else if (event.key === 'End') {
      nextIndex = items.length - 1;
    } else {
      return;
    }

    event.preventDefault();
    const target = items[nextIndex];
    if (target instanceof HTMLElement) target.focus();
  };

  function renderMenuTrigger(id: string, label: string, horizontal = false) {
    const open = openMenuId === id;
    const Icon = horizontal ? Ellipsis : EllipsisVertical;
    return (
      <button
        type="button"
        className="chat-menu-btn ui-rail-menu-trigger"
        ref={(element) => {
          if (element) menuTriggerRefs.current.set(id, element);
          else menuTriggerRefs.current.delete(id);
        }}
        title={label}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? `rail-session-menu-${id}` : undefined}
        onClick={(event) => {
          event.stopPropagation();
          setOpenMenuId(open ? null : id);
          if (!open) focusSessionMenuItem(id);
        }}
        onKeyDown={(event) => {
          if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
          event.preventDefault();
          setOpenMenuId(id);
          focusSessionMenuItem(id, event.key === 'ArrowUp' ? 'last' : 'first');
        }}
      >
        <Icon size={17} aria-hidden="true" />
      </button>
    );
  }

  const renderSession = (session) => {
    const isFavorite = favorites.includes(session.session_id);
    const activity = sessionActivity[session.session_id];
    const activityLabel = getSessionActivityLabel(activity);
    const preview =
      session.last_message && session.last_message.trim() ? session.last_message.trim() : '';
    const title =
      (session.title && session.title.trim()) ||
      preview ||
      (session.session_id || '').slice(0, 16) ||
      t('rail.untitled');
    const showPreview = !!settings.showChatPreview && !!preview && preview !== title;

    return (
      <li
        key={session.session_id}
        className={cn(
          'chat-history-item ui-rail-item',
          currentSessionId === session.session_id && 'active ui-rail-item-active',
          isFavorite && 'favorite ui-rail-item-favorite'
        )}
      >
        {editingSessionId === session.session_id ? (
          <div className="chat-item-main ui-rail-item-main">
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
              autoFocus
              className="chat-rename-input ui-rail-rename-input"
              maxLength={200}
              aria-label={t('rail.rename')}
            />
          </div>
        ) : (
          <button
            type="button"
            className="chat-item-main ui-rail-item-main ui-rail-session-button"
            title={title}
            onClick={() => onSelectSession(session.session_id)}
            aria-current={currentSessionId === session.session_id ? 'page' : undefined}
          >
            <span className="chat-item-title-row ui-rail-title-row">
              <span className="chat-item-title ui-rail-title">{title}</span>
              {session.source?.startsWith('telegram_') && (
                <span className="ui-rail-source-chip">{getSourceLabel(session.source)}</span>
              )}
              {session.is_public && (
                <span className="chat-public-chip ui-rail-public-chip" title={t('rail.publicChat')}>
                  <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                    <circle
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      fill="none"
                      strokeWidth="1.6"
                    />
                    <path
                      d="M2 12h20M12 2c3.5 3.2 3.5 16.8 0 20M7.5 4.5c2.2 2.2 2.2 13 0 15.2M16.5 4.5c-2.2 2.2-2.2 13 0 15.2"
                      stroke="currentColor"
                      fill="none"
                      strokeWidth="1.4"
                    />
                  </svg>
                  {t('rail.public')}
                </span>
              )}
              {activity?.status === 'generating' ? (
                <span
                  className="ui-rail-session-pet"
                  role="img"
                  aria-label={activityLabel}
                  title={activityLabel}
                >
                  <Pet
                    state={
                      currentSessionId === session.session_id && petState !== 'idle'
                        ? petState
                        : 'working'
                    }
                  />
                </span>
              ) : activity?.status ? (
                <span
                  className={cn('ui-rail-status-indicator', `ui-rail-status-${activity.status}`)}
                  title={activityLabel}
                  aria-label={activityLabel}
                />
              ) : null}
            </span>
            {showPreview && <span className="chat-item-preview ui-rail-preview">{preview}</span>}
          </button>
        )}
        <span className="chat-item-details ui-rail-item-details">
          <div className="chat-item-actions ui-rail-item-actions">
            <div
              className={cn(
                'chat-menu-wrapper ui-rail-menu-anchor',
                openMenuId === session.session_id && 'ui-rail-menu-anchor-open'
              )}
            >
              {renderMenuTrigger(session.session_id, t('rail.menu'))}
              {openMenuId === session.session_id && (
                <div
                  className="chat-dropdown-menu ui-rail-menu"
                  id={`rail-session-menu-${session.session_id}`}
                  role="menu"
                  onKeyDown={(event) => handleSessionMenuKeyDown(event, session.session_id)}
                >
                  <RailMenuItem
                    className="menu-item favorite-menu-item"
                    icon={
                      <svg
                        viewBox="0 0 24 24"
                        width="16"
                        height="16"
                        fill="currentColor"
                        aria-hidden="true"
                      >
                        <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
                      </svg>
                    }
                    onClick={(e) => {
                      toggleFavorite(session.session_id, e);
                      setOpenMenuId(null);
                    }}
                  >
                    {isFavorite ? t('rail.favorite.remove') : t('rail.favorite.add')}
                  </RailMenuItem>
                  <RailMenuItem
                    className="menu-item"
                    icon={
                      <svg
                        viewBox="0 0 24 24"
                        width="16"
                        height="16"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                      </svg>
                    }
                    onClick={(e) => {
                      handleRename(session.session_id, e);
                      setOpenMenuId(null);
                    }}
                  >
                    {t('rail.rename')}
                  </RailMenuItem>
                  {!session.is_public && (!session.source || session.source === 'web') && onReferenceChat &&
                    session.session_id !== currentSessionId && (
                    <RailMenuItem
                      className="menu-item"
                      icon={<MessageSquarePlus size={16} aria-hidden="true" />}
                      onClick={(event) => {
                        event.stopPropagation();
                        setOpenMenuId(null);
                        onReferenceChat({ session_id: session.session_id, title });
                      }}
                    >
                      {t('chatReferences.title')}
                    </RailMenuItem>
                  )}
                  {!session.is_public && (!session.source || session.source === 'web') && onCompactSession && (
                    <RailMenuItem
                      className="menu-item"
                      icon={
                        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M5 5h14M5 19h14M12 4v5m-3-1 3 3 3-3m-3 12v-5m-3 1 3-3 3 3" />
                        </svg>
                      }
                      onClick={(event) => {
                        event.stopPropagation();
                        setOpenMenuId(null);
                        void onCompactSession(session.session_id);
                      }}
                    >
                      {t('chatMemory.compact')}
                    </RailMenuItem>
                  )}
                  {!session.is_public && (!session.source || session.source === 'web') && onViewContext && (
                    <RailMenuItem
                      className="menu-item"
                      icon={<BookOpen size={16} aria-hidden="true" />}
                      onClick={(event) => {
                        event.stopPropagation();
                        setOpenMenuId(null);
                        onViewContext(session.session_id);
                      }}
                    >
                      {t('chatMemory.view')}
                    </RailMenuItem>
                  )}
                  <RailMenuItem
                    className="menu-item delete-menu-item"
                    danger
                    icon={
                      <svg
                        viewBox="0 0 24 24"
                        width="16"
                        height="16"
                        fill="currentColor"
                        aria-hidden="true"
                      >
                        <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" />
                      </svg>
                    }
                    onClick={(e) => {
                      handleDelete(session.session_id, e);
                      setOpenMenuId(null);
                    }}
                  >
                    {t('rail.delete')}
                  </RailMenuItem>
                </div>
              )}
            </div>
          </div>
        </span>
      </li>
    );
  };

  return (
    <nav
      className={cn(
        'app-rail ui-rail-shell',
        isExpanded ? 'expanded ui-rail-shell-expanded' : 'ui-rail-shell-collapsed'
      )}
      id="appRail"
      aria-hidden={isMobile && !isExpanded ? true : undefined}
      inert={isMobile && !isExpanded ? true : undefined}
    >
      {isMobile && (
        <div className="ui-rail-mobile-header">
          <button
            type="button"
            className="ui-rail-mobile-brand-home"
            onClick={onNewPersonalChat}
            aria-label={t('projects.personalChat')}
          >
            <img className="ui-rail-mobile-brand" src="/icons/branding/logo.svg" alt="" />
          </button>
          <button
            type="button"
            className="ui-rail-mobile-close"
            data-rail-close
            onClick={onToggle}
            aria-label={t('common.close')}
            title={t('common.close')}
          >
            <X aria-hidden="true" />
          </button>
        </div>
      )}
      {isExpanded && !isMobile && (
        <button type="button" className="ui-rail-agent-brand" onClick={onNewPersonalChat} aria-label={t('projects.personalChat')}>
          <Pet state={petState} />
          <strong>ReMind</strong>
        </button>
      )}
      <div className="rail-toggle-zone ui-rail-toggle-zone">
        <button
          type="button"
          className="rail-toggle-btn ui-rail-toggle-button"
          id="railToggleBtn"
          onClick={onToggle}
          title={isExpanded ? t('rail.collapse') : t('rail.expand')}
          aria-label={isExpanded ? t('rail.collapse') : t('rail.expand')}
        >
          <svg
            className={cn(
              'size-[22px] transition-transform duration-200',
              isExpanded && 'rotate-180'
            )}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M9 18l6-6-6-6" />
          </svg>
        </button>
      </div>

      <div className="rail-quick-actions ui-rail-actions">
        <RailActionButton
          className="rail-icon-btn"
          expanded={isExpanded}
          id="railNewChat"
          label={t('rail.newChat')}
          onClick={onNewChat}
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 5v14M5 12h14" />
          </svg>
        </RailActionButton>
        <RailActionButton
          expanded={isExpanded}
          onClick={
            isExpanded
              ? () => projectHeading.current?.scrollIntoView({ block: 'nearest' })
              : onToggle
          }
          className="rail-icon-btn"
          id="railWorkspace"
          label={t('projects.title')}
          title={t('projects.title')}
          aria-label={t('projects.title')}
        >
          <ProjectIcon />
        </RailActionButton>
        <RailActionButton
          active={currentPath === '/plugins'}
          expanded={isExpanded}
          onClick={onPluginsClick}
          className="rail-icon-btn"
          id="railPlugins"
          label={t('plugins.title')}
          title={t('plugins.title')}
          aria-label={t('plugins.title')}
        >
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3.5v4M12 16.5v4M3.5 12h4M16.5 12h4" />
            <path d="M12 6.5 17.5 12 12 17.5 6.5 12z" />
          </svg>
        </RailActionButton>
        <RailActionButton
          active={currentPath === '/automations'}
          expanded={isExpanded}
          onClick={onAutomationsClick}
          className="rail-icon-btn"
          id="railAutomations"
          label={t('automations.title')}
          title={t('automations.title')}
          aria-label={t('automations.title')}
        >
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 3.5h6M19 5l1.5 1.5M12 9v4l2.5 1.5" />
            <circle cx="12" cy="13" r="7.5" />
          </svg>
        </RailActionButton>
        <div className="ui-rail-minds-section">
          <div className="ui-rail-minds-header">
            <RailActionButton
              active={
                currentPath === '/minds' ||
                currentPath.startsWith('/minds/editor') ||
                !!activeMindId
              }
              className="rail-icon-btn ui-rail-minds-action"
              expanded={isExpanded}
              id="railMinds"
              label={t('rail.minds')}
              onClick={onMindsClick}
              title={t('rail.minds')}
              aria-label={t('rail.minds')}
            >
              <MindRailIcon />
            </RailActionButton>
            {isExpanded && pinnedMinds.length > 0 && (
              <button
                type="button"
                className="ui-rail-pinned-minds-toggle"
                onClick={() => setArePinnedMindsExpanded((expanded) => !expanded)}
                aria-expanded={arePinnedMindsExpanded}
                aria-controls="railPinnedMinds"
                aria-label={arePinnedMindsExpanded ? t('rail.collapse') : t('rail.expand')}
                title={arePinnedMindsExpanded ? t('rail.collapse') : t('rail.expand')}
              >
                <ChevronRight aria-hidden="true" />
              </button>
            )}
          </div>

          {isExpanded && pinnedMinds.length > 0 && (
            <div
              id="railPinnedMinds"
              className={cn(
                'ui-rail-pinned-minds-disclosure',
                arePinnedMindsExpanded && 'ui-rail-pinned-minds-disclosure-expanded'
              )}
              aria-hidden={!arePinnedMindsExpanded}
              inert={!arePinnedMindsExpanded ? true : undefined}
            >
              <div className="ui-rail-pinned-minds-disclosure-inner">
                <div
                  className="ui-rail-pinned-minds ui-rail-pinned-minds-expanded"
                  aria-label={t('minds.pinnedAria')}
                >
                  {pinnedMinds.map((mind) => (
                    <button
                      key={mind.public_id}
                      type="button"
                      className={cn(
                        'ui-rail-pinned-mind ui-rail-pinned-mind-expanded',
                        activeMindId === mind.public_id && 'ui-rail-pinned-mind-active'
                      )}
                      title={mind.name}
                      onClick={() => onSelectMind?.(mind)}
                    >
                      <span className="ui-rail-pinned-mind-avatar">{getMindInitials(mind)}</span>
                      <span className="ui-rail-pinned-mind-label">{mind.name}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
        {user?.is_admin && (
          <RailActionButton
            active={currentPath === '/admin' || currentPath.startsWith('/admin/')}
            className="rail-icon-btn"
            expanded={isExpanded}
            id="railAdmin"
            label={t('rail.admin')}
            onClick={onAdminClick}
            title={t('rail.admin')}
            aria-label={t('rail.admin')}
          >
            <ShieldCheck size={20} />
          </RailActionButton>
        )}
      </div>

      {isExpanded && (
        <div className="rail-search-container ui-rail-search-wrap">
          <div className="rail-search-row">
            <input
              type="text"
              className="rail-search-input ui-rail-search-input"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('rail.searchPlaceholder')}
              aria-label={t('rail.searchInput')}
            />
            <div className="rail-source-filter" ref={sourceFilterRef}>
              <button
                type="button"
                className={cn(
                  'rail-source-filter-trigger',
                  sourceFilter !== 'all' && 'rail-source-filter-trigger-active'
                )}
                aria-label={t('rail.channelFilter.label')}
                aria-haspopup="menu"
                aria-expanded={isSourceFilterOpen}
                onClick={() => setIsSourceFilterOpen((open) => !open)}
              >
                <ListFilter size={19} strokeWidth={2} aria-hidden="true" />
              </button>
              {isSourceFilterOpen && (
                <div
                  className="rail-source-filter-menu"
                  role="menu"
                  aria-label={t('rail.channelFilter.label')}
                >
                  {['all', 'web', 'telegram'].map((filter) => (
                    <button
                      key={filter}
                      type="button"
                      role="menuitemradio"
                      className={cn(
                        'rail-source-filter-option',
                        sourceFilter === filter && 'rail-source-filter-option-active'
                      )}
                      aria-checked={sourceFilter === filter}
                      onClick={() => {
                        setSourceFilter(filter);
                        setIsSourceFilterOpen(false);
                      }}
                    >
                      <span>{t(`rail.channelFilter.${filter}`)}</span>
                      {sourceFilter === filter && (
                        <Check size={16} strokeWidth={2.2} aria-hidden="true" />
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <div
        className={cn(
          'rail-content-wrapper rail-chat-container ui-rail-content',
          isExpanded ? 'ui-rail-content-visible' : 'ui-rail-content-hidden'
        )}
      >
        <ul id="chatHistoryList" className="rail-chat-list ui-rail-list ui-scrollbar-thin">
          {isExpanded && (
            <li className="ui-rail-projects">
              <div className="ui-rail-projects-heading" ref={projectHeading}>
                <span>{t('projects.title')}</span>
                <button
                  type="button"
                  aria-label={t('projects.new')}
                  onClick={() => setProjectEditor({ name: '' })}
                >
                  <ProjectIcon add />
                </button>
              </div>
              {projectEditor && (
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    void changeProject(async () => {
                      const project = await projectStore.save(projectEditor.name.trim(), projectEditor.id);
                      if (!projectEditor.id) onOpenProject(project.id);
                      setProjectEditor(null);
                    });
                  }}
                >
                  <input
                    aria-label={t('projects.name')}
                    maxLength={80}
                    autoFocus
                    required
                    value={projectEditor.name}
                    onChange={(event) =>
                      setProjectEditor({ ...projectEditor, name: event.target.value })
                    }
                  />
                  <button
                    type="submit"
                    disabled={projectBusy || !projectEditor.name.trim()}
                    aria-label={t('projects.save')}
                  >
                    <Check size={16} />
                  </button>
                  <button
                    type="button"
                    onClick={() => setProjectEditor(null)}
                    aria-label={t('projects.cancel')}
                  >
                    <X size={16} />
                  </button>
                </form>
              )}
              {(projectError || projectStore.loadError) && (
                <p role="alert">{t('projects.failed')}</p>
              )}
              {projects.map((project) => {
                const chats = filteredSessions.filter((item) => item.workspace_id === project.id);
                const active = project.id === activeProjectId;
                const expanded = projectExpansion.get(project.id) ?? (active || Boolean(searchQuery.trim()));
                const chatsId = 'project-chats-' + project.id;
                const menuId = 'project-' + project.id;
                const menuOpen = openMenuId === menuId;
                const currentChat = localSessions.find((item) => item.session_id === currentSessionId);
                const canMoveChat = currentChat && !currentChat.is_public &&
                  (!currentChat.source || currentChat.source === 'web') &&
                  currentChat.workspace_id !== project.id;
                const folder = expanded && chats.length > 0
                  ? <FolderOpen size={17} strokeWidth={1.7} aria-hidden="true" />
                  : <ProjectIcon />;

                return (
                  <div key={project.id} className={cn('ui-rail-project', active && 'is-active')}>
                    <div className={cn('ui-rail-project-row', menuOpen && 'is-menu-open')}>
                      {chats.length > 0 ? (
                        <button
                          type="button"
                          className="ui-rail-project-fold"
                          title={t('projects.showChats', { name: project.name })}
                          aria-label={t('projects.showChats', { name: project.name })}
                          aria-expanded={expanded}
                          aria-controls={chatsId}
                          onClick={() => setProjectExpansion((previous) => new Map(previous).set(project.id, !expanded))}
                        >
                          <span className="ui-rail-project-folder">{folder}</span>
                          <ChevronRight className="ui-rail-project-chevron" size={16} aria-hidden="true" />
                        </button>
                      ) : (
                        <span className="ui-rail-project-fold ui-rail-project-folder" aria-hidden="true">{folder}</span>
                      )}
                      <button
                        type="button"
                        className="ui-rail-project-name"
                        aria-current={active ? 'true' : undefined}
                        onClick={() => onOpenProject(project.id)}
                        title={project.name}
                      >
                        <span>{project.name}</span>
                      </button>
                      <div className="ui-rail-project-actions">
                        <div className={cn('chat-menu-wrapper ui-rail-menu-anchor', menuOpen && 'ui-rail-menu-anchor-open')}>
                          {renderMenuTrigger(menuId, t('projects.actions', { name: project.name }), true)}
                          {menuOpen && (
                            <div
                              className="chat-dropdown-menu ui-rail-menu ui-rail-project-menu"
                              id={'rail-session-menu-' + menuId}
                              role="menu"
                              onKeyDown={(event) => handleSessionMenuKeyDown(event, menuId)}
                            >
                              <RailMenuItem
                                icon={<Settings2 size={16} aria-hidden="true" />}
                                onClick={() => {
                                  setOpenMenuId(null);
                                  onProjectSettings(project.id);
                                }}
                              >
                                {t('projects.details')}
                              </RailMenuItem>
                              <RailMenuItem
                                icon={<Pencil size={16} aria-hidden="true" />}
                                onClick={() => {
                                  setOpenMenuId(null);
                                  setProjectEditor(project);
                                }}
                              >
                                {t('rail.rename')}
                              </RailMenuItem>
                              {canMoveChat && (
                                <RailMenuItem
                                  icon={<ArrowRight size={16} aria-hidden="true" />}
                                  onClick={() => {
                                    setOpenMenuId(null);
                                    void changeProject(async () => {
                                      await projectStore.moveChat(currentChat.session_id, project.id);
                                      onSessionMoved(currentChat.session_id, project.id);
                                      setLocalSessions((items) => items.map((item) =>
                                        item.session_id === currentChat.session_id
                                          ? { ...item, workspace_id: project.id }
                                          : item
                                      ));
                                    });
                                  }}
                                >
                                  {t('projects.moveCurrent')}
                                </RailMenuItem>
                              )}
                              <RailMenuItem
                                danger
                                icon={<Trash2 size={16} aria-hidden="true" />}
                                onClick={() => {
                                  setOpenMenuId(null);
                                  if (!window.confirm(t('projects.confirmRemove', { name: project.name }))) return;
                                  void changeProject(async () => {
                                    await projectStore.remove(project.id);
                                    onProjectsChanged();
                                    setLocalSessions((items) => items.map((item) =>
                                      item.workspace_id === project.id ? { ...item, workspace_id: null } : item
                                    ));
                                  });
                                }}
                              >
                                {t('rail.delete')}
                              </RailMenuItem>
                            </div>
                          )}
                        </div>
                        <button
                          type="button"
                          disabled={projectBusy}
                          className="ui-rail-project-new"
                          aria-label={t('projects.newChatInProject', { name: project.name })}
                          title={t('projects.newChatInProject', { name: project.name })}
                          onClick={() => onOpenProject(project.id)}
                        >
                          <SquarePen size={16} strokeWidth={1.7} aria-hidden="true" />
                        </button>
                      </div>
                    </div>
                    <ul className="ui-rail-project-chats" id={chatsId} hidden={!expanded || chats.length === 0}>
                      {expanded && chats.map(renderSession)}
                    </ul>
                  </div>
                );
              })}
            </li>
          )}
          {filteredSessions
            .filter((session) => !projectIds.has(session.workspace_id))
            .map(renderSession)}

          {filteredSessions.length === 0 && (
            <li className="empty-history-message ui-rail-empty">
              {effectiveQuery ? t('rail.noResults') : t('rail.emptyHistory')}
            </li>
          )}
        </ul>
      </div>

      <div className="rail-actions-bottom ui-rail-footer">
        <RailActionButton
          className="rail-btn-secondary ui-rail-footer-button"
          expanded={isExpanded}
          id="railSettings"
          label={t('rail.settings')}
          onClick={onSettingsClick}
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </RailActionButton>
      </div>
    </nav>
  );
};

export default AppRail;
