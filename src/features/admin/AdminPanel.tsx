import { useCallback, useDeferredValue, useEffect, useMemo, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import {
    Activity,
    AlertTriangle,
    BadgeCheck,
    Ban,
    BrainCircuit,
    CheckCircle2,
    ClipboardList,
    Clock,
    Cpu,
    Database,
    Gauge,
    HardDrive,
    Lock,
    Search,
    Server,
    Shield,
    ShieldCheck,
    ShieldPlus,
    Sparkles,
    TrendingUp,
    Unlock,
    UserCheck,
    Users,
    XCircle,
} from 'lucide-react';
import {
    apiService,
    type AdminMind,
    type AdminOverview,
    type AdminPagination,
    type AdminUser,
} from '../../services/api';
import { useAuth } from '../../context/AuthContext';
import { cn } from '../../utils/cn';

type AdminTab = 'overview' | 'operations' | 'users' | 'minds' | 'server';
type UserRestrictionField = 'is_banned' | 'is_blocked';
type RestrictionDraft = {
    user: AdminUser;
    field: UserRestrictionField;
    reason: string;
    preset: string;
    customUntil: string;
};

const USER_STATUS_OPTIONS = [
    { id: 'all', label: 'Все' },
    { id: 'active', label: 'Активные' },
    { id: 'admin', label: 'Админы' },
    { id: 'restricted', label: 'Ограничены' },
    { id: 'banned', label: 'Бан' },
    { id: 'blocked', label: 'Блок' },
    { id: 'unconfirmed', label: 'Не подтверждены' },
];

const MIND_STATUS_OPTIONS = [
    { id: 'all', label: 'Все' },
    { id: 'featured', label: 'Главная' },
    { id: 'needs_review', label: 'Review' },
    { id: 'banned', label: 'Бан' },
    { id: 'verified', label: 'Verified' },
    { id: 'store', label: 'Store' },
    { id: 'private', label: 'Private' },
    { id: 'link', label: 'Link' },
];

const RESTRICTION_PRESETS = [
    { id: '1h', label: '1 час', hours: 1 },
    { id: '24h', label: '24 часа', hours: 24 },
    { id: '7d', label: '7 дней', hours: 24 * 7 },
    { id: '30d', label: '30 дней', hours: 24 * 30 },
    { id: 'forever', label: 'Бессрочно', hours: null },
    { id: 'custom', label: 'Свой срок', hours: null },
];

function getErrorMessage(error: unknown, fallback: string): string {
    if (error instanceof Error && error.message) {
        return error.message;
    }
    return fallback;
}

function formatNumber(value: number | undefined): string {
    return new Intl.NumberFormat('ru-RU').format(value || 0);
}

function formatDate(value?: string | null): string {
    if (!value) return '—';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return '—';
    return new Intl.DateTimeFormat('ru-RU', {
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        month: 'short',
        year: 'numeric',
    }).format(parsed);
}

function formatDateShort(value?: string | null): string {
    if (!value) return 'бессрочно';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return '—';
    return new Intl.DateTimeFormat('ru-RU', {
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        month: 'short',
    }).format(parsed);
}

function formatDuration(seconds: number | undefined): string {
    const total = Math.max(0, Math.floor(seconds || 0));
    const days = Math.floor(total / 86_400);
    const hours = Math.floor((total % 86_400) / 3_600);
    const minutes = Math.floor((total % 3_600) / 60);
    if (days > 0) return `${days}д ${hours}ч`;
    if (hours > 0) return `${hours}ч ${minutes}м`;
    return `${minutes}м`;
}

function formatBytes(value?: number | null): string {
    if (!value) return '—';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = value;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex += 1;
    }
    const unit = units[unitIndex] || 'B';
    return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${unit}`;
}

function formatPercent(value?: number): string {
    return `${Math.max(0, Math.min(100, Math.round(value || 0)))}%`;
}

function userStatus(user: AdminUser): { label: string; tone: string } {
    if (user.is_banned) return { label: 'Ban', tone: 'danger' };
    if (user.is_blocked) return { label: 'Blocked', tone: 'warning' };
    if (!user.is_confirmed) return { label: 'Pending', tone: 'muted' };
    return { label: 'Active', tone: 'success' };
}

function restrictionInfo(user: AdminUser): { reason: string | null; until: string | null; label: string } | null {
    if (user.is_banned) {
        return {
            label: 'Ban',
            reason: user.ban_reason || user.moderation_reason || null,
            until: user.banned_until ?? null,
        };
    }
    if (user.is_blocked) {
        return {
            label: 'Block',
            reason: user.block_reason || user.moderation_reason || null,
            until: user.blocked_until ?? null,
        };
    }
    return null;
}

function buildRestrictionUntil(preset: string, customUntil: string): string | null {
    const selectedPreset = RESTRICTION_PRESETS.find((item) => item.id === preset);
    if (selectedPreset?.hours) {
        return new Date(Date.now() + selectedPreset.hours * 3_600_000).toISOString();
    }
    if (preset === 'custom' && customUntil) {
        const parsed = new Date(customUntil);
        return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString();
    }
    return null;
}

function normalizeTone(tone?: string): string {
    if (tone === 'danger' || tone === 'warning' || tone === 'accent' || tone === 'success') {
        return tone;
    }
    return 'muted';
}

function defaultPagination(): AdminPagination {
    return { page: 1, page_size: 25, total: 0 };
}

function PaginationControls({
    disabled,
    onPageChange,
    pagination,
}: {
    disabled: boolean;
    onPageChange: (page: number) => void;
    pagination: AdminPagination;
}) {
    const pageCount = Math.max(1, Math.ceil(pagination.total / pagination.page_size));
    return (
        <div className="admin-pagination">
            <span>
                {formatNumber(pagination.total)} записей · {pagination.page}/{pageCount}
            </span>
            <div>
                <button
                    type="button"
                    disabled={disabled || pagination.page <= 1}
                    onClick={() => onPageChange(pagination.page - 1)}
                >
                    Назад
                </button>
                <button
                    type="button"
                    disabled={disabled || pagination.page >= pageCount}
                    onClick={() => onPageChange(pagination.page + 1)}
                >
                    Вперед
                </button>
            </div>
        </div>
    );
}

function MetricTile({
    icon,
    label,
    value,
}: {
    icon: ReactNode;
    label: string;
    value: number | string | undefined;
}) {
    return (
        <div className="admin-metric-tile">
            <span>{icon}</span>
            <div>
                <strong>{typeof value === 'number' ? formatNumber(value) : value || '—'}</strong>
                <small>{label}</small>
            </div>
        </div>
    );
}

export default function AdminPanel({ isAuthenticated, onOpenAuth }: {
    isAuthenticated: boolean;
    onOpenAuth: () => void;
}) {
    const { user } = useAuth();
    const [activeTab, setActiveTab] = useState<AdminTab>('overview');
    const [overview, setOverview] = useState<AdminOverview | null>(null);
    const [users, setUsers] = useState<AdminUser[]>([]);
    const [minds, setMinds] = useState<AdminMind[]>([]);
    const [userPagination, setUserPagination] = useState<AdminPagination>(() => defaultPagination());
    const [mindPagination, setMindPagination] = useState<AdminPagination>(() => defaultPagination());
    const [userQuery, setUserQuery] = useState('');
    const [mindQuery, setMindQuery] = useState('');
    const [userStatusFilter, setUserStatusFilter] = useState('all');
    const [mindStatusFilter, setMindStatusFilter] = useState('all');
    const [loading, setLoading] = useState(false);
    const [busyId, setBusyId] = useState<string | null>(null);
    const [error, setError] = useState('');
    const [restrictionDraft, setRestrictionDraft] = useState<RestrictionDraft | null>(null);
    const deferredUserQuery = useDeferredValue(userQuery.trim());
    const deferredMindQuery = useDeferredValue(mindQuery.trim());

    const canAccessAdmin = Boolean(isAuthenticated && user?.is_admin);
    const canAssignAdmins = Boolean(overview?.admin.is_super_admin || user?.is_super_admin);

    const jumpToUsers = useCallback((status: string) => {
        setUserStatusFilter(status);
        setActiveTab('users');
    }, []);

    const jumpToMinds = useCallback((status: string) => {
        setMindStatusFilter(status);
        setActiveTab('minds');
    }, []);

    const loadOverview = useCallback(async () => {
        if (!canAccessAdmin) return;
        setError('');
        try {
            const data = await apiService.getAdminOverview();
            setOverview(data);
        } catch (loadError) {
            setError(getErrorMessage(loadError, 'Не удалось загрузить обзор админки'));
        }
    }, [canAccessAdmin]);

    const loadUsers = useCallback(async (page = 1) => {
        if (!canAccessAdmin) return;
        setLoading(true);
        setError('');
        try {
            const data = await apiService.listAdminUsers({
                page,
                pageSize: userPagination.page_size,
                q: deferredUserQuery,
                status: userStatusFilter,
            });
            setUsers(data.users);
            setUserPagination(data.pagination);
        } catch (loadError) {
            setError(getErrorMessage(loadError, 'Не удалось загрузить пользователей'));
        } finally {
            setLoading(false);
        }
    }, [canAccessAdmin, deferredUserQuery, userPagination.page_size, userStatusFilter]);

    const loadMinds = useCallback(async (page = 1) => {
        if (!canAccessAdmin) return;
        setLoading(true);
        setError('');
        try {
            const data = await apiService.listAdminMinds({
                page,
                pageSize: mindPagination.page_size,
                q: deferredMindQuery,
                status: mindStatusFilter,
            });
            setMinds(data.minds);
            setMindPagination(data.pagination);
        } catch (loadError) {
            setError(getErrorMessage(loadError, 'Не удалось загрузить minds'));
        } finally {
            setLoading(false);
        }
    }, [canAccessAdmin, deferredMindQuery, mindPagination.page_size, mindStatusFilter]);

    useEffect(() => {
        void loadOverview();
    }, [loadOverview]);

    useEffect(() => {
        if (activeTab === 'users') {
            void loadUsers(1);
        }
    }, [activeTab, deferredUserQuery, loadUsers, userStatusFilter]);

    useEffect(() => {
        if (activeTab === 'minds') {
            void loadMinds(1);
        }
    }, [activeTab, deferredMindQuery, loadMinds, mindStatusFilter]);

    const replaceUser = useCallback((nextUser: AdminUser) => {
        setUsers((current) => current.map((item) => (item.id === nextUser.id ? nextUser : item)));
    }, []);

    const replaceMind = useCallback((nextMind: AdminMind) => {
        setMinds((current) => current.map((item) => (item.public_id === nextMind.public_id ? nextMind : item)));
    }, []);

    const openRestrictionDraft = useCallback((target: AdminUser, field: UserRestrictionField) => {
        setRestrictionDraft({
            user: target,
            field,
            reason: target.moderation_reason || '',
            preset: '24h',
            customUntil: '',
        });
    }, []);

    const clearUserRestriction = useCallback(async (
        target: AdminUser,
        field: UserRestrictionField
    ) => {
        const promptLabel = field === 'is_banned' ? 'бан' : 'блокировку';
        const confirmed = window.confirm(`Снять ${promptLabel} с ${target.username}?`);
        if (!confirmed) return;
        setBusyId(`user-${target.id}-${field}`);
        setError('');
        try {
            const nextUser = await apiService.updateAdminUser(target.id, {
                [field]: false,
            });
            replaceUser(nextUser);
            void loadOverview();
        } catch (updateError) {
            setError(getErrorMessage(updateError, 'Не удалось обновить пользователя'));
        } finally {
            setBusyId(null);
        }
    }, [loadOverview, replaceUser]);

    const submitRestrictionDraft = useCallback(async () => {
        if (!restrictionDraft) return;
        const reason = restrictionDraft.reason.trim();
        if (!reason) {
            setError('Укажите причину ограничения');
            return;
        }
        if (restrictionDraft.preset === 'custom' && !restrictionDraft.customUntil) {
            setError('Укажите дату окончания ограничения');
            return;
        }
        const until = buildRestrictionUntil(restrictionDraft.preset, restrictionDraft.customUntil);
        if (restrictionDraft.preset === 'custom' && !until) {
            setError('Укажите корректную дату окончания ограничения');
            return;
        }
        const { user: target, field } = restrictionDraft;
        const payload =
            field === 'is_banned'
                ? {
                      is_banned: true,
                      ban_reason: reason,
                      moderation_reason: reason,
                      banned_until: until,
                  }
                : {
                      is_blocked: true,
                      block_reason: reason,
                      moderation_reason: reason,
                      blocked_until: until,
                  };

        setBusyId(`user-${target.id}-${field}`);
        setError('');
        try {
            const nextUser = await apiService.updateAdminUser(target.id, payload);
            replaceUser(nextUser);
            setRestrictionDraft(null);
            void loadOverview();
        } catch (updateError) {
            setError(getErrorMessage(updateError, 'Не удалось обновить пользователя'));
        } finally {
            setBusyId(null);
        }
    }, [loadOverview, replaceUser, restrictionDraft]);

    const updateAdminRole = useCallback(async (target: AdminUser) => {
        const nextValue = !target.is_admin;
        const confirmed = window.confirm(
            nextValue
                ? `Назначить ${target.username} администратором?`
                : `Снять права администратора у ${target.username}?`
        );
        if (!confirmed) return;

        setBusyId(`user-${target.id}-admin`);
        setError('');
        try {
            const nextUser = await apiService.setAdminRole(target.id, nextValue);
            replaceUser(nextUser);
            void loadOverview();
        } catch (updateError) {
            setError(getErrorMessage(updateError, 'Не удалось изменить роль'));
        } finally {
            setBusyId(null);
        }
    }, [loadOverview, replaceUser]);

    const updateMindFlag = useCallback(async (
        target: AdminMind,
        field: 'is_banned' | 'is_featured' | 'is_verified'
    ) => {
        const nextValue = !target[field];
        let reason: string | null | undefined;
        if (field === 'is_banned' && nextValue) {
            reason = window.prompt('Причина бана mind', target.moderation_reason || '');
            if (reason === null) return;
        }

        setBusyId(`mind-${target.public_id}-${field}`);
        setError('');
        try {
            const nextMind = await apiService.updateAdminMind(target.public_id, {
                [field]: nextValue,
                ...(reason !== undefined ? { moderation_reason: reason } : {}),
            });
            replaceMind(nextMind);
            void loadOverview();
        } catch (updateError) {
            setError(getErrorMessage(updateError, 'Не удалось обновить mind'));
        } finally {
            setBusyId(null);
        }
    }, [loadOverview, replaceMind]);

    const serverRows = useMemo(() => {
        if (!overview) return [];
        return [
            {
                icon: <Database size={18} />,
                label: 'Database',
                value: overview.server.components.database.status,
            },
            {
                icon: <Activity size={18} />,
                label: 'Redis',
                value: overview.server.components.redis.status,
            },
            {
                icon: <Gauge size={18} />,
                label: 'Uptime',
                value: formatDuration(overview.server.uptime_seconds),
            },
            {
                icon: <HardDrive size={18} />,
                label: 'Memory',
                value: formatBytes(overview.server.process.memory.max_rss_bytes),
            },
            {
                icon: <Cpu size={18} />,
                label: 'CPU / threads',
                value: `${overview.server.process.cpu_count || '—'} / ${overview.server.process.thread_count || '—'}`,
            },
            {
                icon: <Clock size={18} />,
                label: 'Snapshot',
                value: formatDateShort(overview.server.timestamp),
            },
        ];
    }, [overview]);

    if (!isAuthenticated) {
        return (
            <section className="admin-page">
                <div className="admin-access-panel">
                    <Shield size={34} />
                    <h1>Admin</h1>
                    <p>Войдите в аккаунт администратора.</p>
                    <button type="button" onClick={onOpenAuth}>
                        Войти
                    </button>
                </div>
            </section>
        );
    }

    if (!canAccessAdmin) {
        return (
            <section className="admin-page">
                <div className="admin-access-panel">
                    <Lock size={34} />
                    <h1>Доступ закрыт</h1>
                    <p>{["Ваш вайб не соответствует требованиям безопасности.", "Доступ закрыт. Причина: подозрительно уверенно зашёл.", "Система обнаружила бедность в заголовках запроса.", "Я вообще фронтенд на GitHub Pages деплоил."][Math.floor(Math.random() * 4)]}</p>                </div>
            </section>
        );
    }

    return (
        <section className="admin-page">
            <div className="admin-heading">
                <div>
                    <div className="admin-title-row">
                        <ShieldCheck size={30} />
                        <h1>Admin</h1>
                    </div>
                    <p>Управление доступом, minds, нагрузкой и состоянием сервера.</p>
                </div>
                <button type="button" className="admin-refresh-button" onClick={() => void loadOverview()}>
                    <Activity size={17} />
                    Обновить
                </button>
            </div>

            <div className="admin-tabs" role="tablist" aria-label="Admin sections">
                <button
                    type="button"
                    className={cn(activeTab === 'overview' && 'active')}
                    onClick={() => setActiveTab('overview')}
                >
                    <Gauge size={16} />
                    Обзор
                </button>
                <button
                    type="button"
                    className={cn(activeTab === 'operations' && 'active')}
                    onClick={() => setActiveTab('operations')}
                >
                    <ClipboardList size={16} />
                    Операции
                </button>
                <button
                    type="button"
                    className={cn(activeTab === 'users' && 'active')}
                    onClick={() => setActiveTab('users')}
                >
                    <Users size={16} />
                    Аккаунты
                </button>
                <button
                    type="button"
                    className={cn(activeTab === 'minds' && 'active')}
                    onClick={() => setActiveTab('minds')}
                >
                    <BrainCircuit size={16} />
                    Minds
                </button>
                <button
                    type="button"
                    className={cn(activeTab === 'server' && 'active')}
                    onClick={() => setActiveTab('server')}
                >
                    <Server size={16} />
                    Сервер
                </button>
            </div>

            {error && <div className="admin-error">{error}</div>}

            {restrictionDraft && (
                <div className="admin-restriction-editor" role="dialog" aria-modal="true">
                    <div className="admin-restriction-editor-header">
                        <div>
                            <strong>
                                {restrictionDraft.field === 'is_banned' ? 'Бан пользователя' : 'Блокировка пользователя'}
                            </strong>
                            <span>{restrictionDraft.user.username} · {restrictionDraft.user.email}</span>
                        </div>
                        <button type="button" onClick={() => setRestrictionDraft(null)}>
                            Закрыть
                        </button>
                    </div>
                    <label>
                        Причина
                        <textarea
                            value={restrictionDraft.reason}
                            maxLength={280}
                            onChange={(event) => setRestrictionDraft((current) => (
                                current ? { ...current, reason: event.target.value } : current
                            ))}
                            placeholder="Например: спам, нарушение правил, подозрительная активность"
                        />
                    </label>
                    <div className="admin-restriction-presets" role="radiogroup" aria-label="Срок ограничения">
                        {RESTRICTION_PRESETS.map((preset) => (
                            <button
                                key={preset.id}
                                type="button"
                                className={cn(restrictionDraft.preset === preset.id && 'active')}
                                onClick={() => setRestrictionDraft((current) => (
                                    current ? { ...current, preset: preset.id } : current
                                ))}
                            >
                                {preset.label}
                            </button>
                        ))}
                    </div>
                    {restrictionDraft.preset === 'custom' && (
                        <label>
                            Окончание
                            <input
                                type="datetime-local"
                                value={restrictionDraft.customUntil}
                                onChange={(event) => setRestrictionDraft((current) => (
                                    current ? { ...current, customUntil: event.target.value } : current
                                ))}
                            />
                        </label>
                    )}
                    <div className="admin-restriction-actions">
                        <span>
                            Пользователь увидит причину и срок при входе или следующем запросе.
                        </span>
                        <button
                            type="button"
                            disabled={busyId === `user-${restrictionDraft.user.id}-${restrictionDraft.field}`}
                            onClick={() => void submitRestrictionDraft()}
                        >
                            Применить
                        </button>
                    </div>
                </div>
            )}

            {activeTab === 'overview' && (
                <div className="admin-section">
                    <div className="admin-command-strip">
                        <div>
                            <span>Health score</span>
                            <strong>{formatPercent(overview?.operations.health.score)}</strong>
                            <small>{overview?.operations.health.level || '—'}</small>
                        </div>
                        <div>
                            <span>Очередь модерации</span>
                            <strong>{formatNumber(overview?.operations.queues.unverified_store_minds)}</strong>
                            <small>Store minds без verified</small>
                        </div>
                        <div>
                            <span>Рост за 7 дней</span>
                            <strong>+{formatNumber(overview?.operations.growth_7d.users)}</strong>
                            <small>новых пользователей</small>
                        </div>
                        <button type="button" onClick={() => setActiveTab('operations')}>
                            <ClipboardList size={16} />
                            Открыть command center
                        </button>
                    </div>
                    <div className="admin-overview-grid">
                        <MetricTile icon={<Users size={18} />} label="Пользователей" value={overview?.stats.users.total} />
                        <MetricTile icon={<ShieldPlus size={18} />} label="Администраторов" value={overview?.stats.users.admins} />
                        <MetricTile icon={<BrainCircuit size={18} />} label="Minds всего" value={overview?.stats.minds.total} />
                        <MetricTile icon={<Sparkles size={18} />} label="На главной" value={overview?.stats.minds.featured} />
                        <MetricTile icon={<Ban size={18} />} label="Банов аккаунтов" value={overview?.stats.users.banned} />
                        <MetricTile icon={<Lock size={18} />} label="Блокировок" value={overview?.stats.users.blocked} />
                        <MetricTile icon={<Activity size={18} />} label="Сессий за 24ч" value={overview?.stats.sessions.updated_24h} />
                        <MetricTile icon={<Server size={18} />} label="Статус сервера" value={overview?.server.status} />
                    </div>
                </div>
            )}

            {activeTab === 'operations' && (
                <div className="admin-ops-grid">
                    <div className="admin-ops-health">
                        <div>
                            <span>Operational health</span>
                            <strong>{formatPercent(overview?.operations.health.score)}</strong>
                            <small>{overview?.operations.health.level || '—'}</small>
                        </div>
                        <div
                            className="admin-health-ring"
                            style={{ '--admin-health': `${overview?.operations.health.score || 0}%` } as CSSProperties}
                            aria-label="Operational health score"
                        />
                    </div>

                    <div className="admin-ops-panel">
                        <h2>
                            <AlertTriangle size={17} />
                            Action center
                        </h2>
                        <div className="admin-alert-list">
                            {(overview?.operations.alerts || []).map((alert) => (
                                <div className={cn('admin-alert-item', `tone-${normalizeTone(alert.tone)}`)} key={`${alert.title}-${alert.detail}`}>
                                    <strong>{alert.title}</strong>
                                    <span>{alert.detail}</span>
                                    <small>{alert.action}</small>
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className="admin-ops-panel">
                        <h2>
                            <ClipboardList size={17} />
                            Moderation queues
                        </h2>
                        <div className="admin-queue-grid">
                            <button type="button" onClick={() => jumpToUsers('unconfirmed')}>
                                <strong>{formatNumber(overview?.operations.queues.unconfirmed_users)}</strong>
                                <span>Email pending</span>
                            </button>
                            <button type="button" onClick={() => jumpToUsers('restricted')}>
                                <strong>{formatNumber(overview?.operations.queues.restricted_users)}</strong>
                                <span>Restricted users</span>
                            </button>
                            <button type="button" onClick={() => jumpToMinds('store')}>
                                <strong>{formatNumber(overview?.operations.queues.store_minds)}</strong>
                                <span>Store minds</span>
                            </button>
                            <button type="button" onClick={() => jumpToMinds('needs_review')}>
                                <strong>{formatNumber(overview?.operations.queues.unverified_store_minds)}</strong>
                                <span>Needs review</span>
                            </button>
                            <button type="button" onClick={() => jumpToMinds('banned')}>
                                <strong>{formatNumber(overview?.operations.queues.banned_minds)}</strong>
                                <span>Banned minds</span>
                            </button>
                        </div>
                    </div>

                    <div className="admin-ops-panel">
                        <h2>
                            <TrendingUp size={17} />
                            Growth 7d
                        </h2>
                        <div className="admin-growth-row">
                            <div>
                                <strong>+{formatNumber(overview?.operations.growth_7d.users)}</strong>
                                <span>Users</span>
                            </div>
                            <div>
                                <strong>+{formatNumber(overview?.operations.growth_7d.minds)}</strong>
                                <span>Minds</span>
                            </div>
                            <div>
                                <strong>+{formatNumber(overview?.operations.growth_7d.sessions)}</strong>
                                <span>Sessions</span>
                            </div>
                        </div>
                    </div>

                    <div className="admin-ops-panel admin-ops-wide">
                        <h2>
                            <UserCheck size={17} />
                            High activity accounts
                        </h2>
                        <div className="admin-compact-list">
                            {(overview?.operations.top_users || []).map((item) => (
                                <button
                                    type="button"
                                    key={item.id}
                                    onClick={() => {
                                        setUserQuery(item.email);
                                        setActiveTab('users');
                                    }}
                                >
                                    <span>
                                        <strong>{item.username}</strong>
                                        <small>{item.email}</small>
                                    </span>
                                    <span>
                                        <strong>{formatNumber(item.chat_count)}</strong>
                                        <small>sessions</small>
                                    </span>
                                    <span>
                                        <strong>{formatNumber(item.mind_count)}</strong>
                                        <small>minds</small>
                                    </span>
                                    {item.is_restricted && <em>restricted</em>}
                                </button>
                            ))}
                            {overview?.operations.top_users.length === 0 && (
                                <div className="admin-empty">Активность пока не накоплена</div>
                            )}
                        </div>
                    </div>

                    <div className="admin-ops-panel admin-ops-wide">
                        <h2>
                            <Clock size={17} />
                            Audit stream
                        </h2>
                        <div className="admin-audit-list">
                            {(overview?.operations.recent_audit || []).map((event, index) => (
                                <div className={cn('admin-audit-item', `tone-${normalizeTone(event.severity === 'warning' ? 'warning' : 'muted')}`)} key={`${event.timestamp}-${event.event_type}-${index}`}>
                                    <span>
                                        <strong>{event.event_type}</strong>
                                        <small>{event.method || '—'} {event.endpoint || '—'}</small>
                                    </span>
                                    <span>
                                        <strong>{formatDate(event.timestamp)}</strong>
                                        <small>{event.client_type || event.user_hash || 'system'}</small>
                                    </span>
                                </div>
                            ))}
                            {overview?.operations.recent_audit.length === 0 && (
                                <div className="admin-empty">Audit events пока не найдены</div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {activeTab === 'users' && (
                <div className="admin-section">
                    <div className="admin-controls">
                        <div className="admin-search">
                            <Search size={18} />
                            <input
                                value={userQuery}
                                onChange={(event) => setUserQuery(event.target.value)}
                                placeholder="Поиск по имени, email, username"
                                maxLength={100}
                            />
                        </div>
                        <div className="admin-filter-row">
                            {USER_STATUS_OPTIONS.map((option) => (
                                <button
                                    key={option.id}
                                    type="button"
                                    className={cn(userStatusFilter === option.id && 'active')}
                                    onClick={() => setUserStatusFilter(option.id)}
                                >
                                    {option.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div className="admin-table-wrap">
                        <table className="admin-table">
                            <thead>
                                <tr>
                                    <th>Пользователь</th>
                                    <th>Статус</th>
                                    <th>Ограничение</th>
                                    <th>Роль</th>
                                    <th>Активность</th>
                                    <th>Создан</th>
                                    <th>Действия</th>
                                </tr>
                            </thead>
                            <tbody>
                                {users.map((item) => {
                                    const status = userStatus(item);
                                    const restriction = restrictionInfo(item);
                                    return (
                                        <tr key={item.id}>
                                            <td>
                                                <strong>{item.username}</strong>
                                                <span>{item.email}</span>
                                            </td>
                                            <td>
                                                <span className={cn('admin-status-chip', `tone-${status.tone}`)}>
                                                    {status.label}
                                                </span>
                                            </td>
                                            <td>
                                                {restriction ? (
                                                    <div className="admin-restriction-cell">
                                                        <strong>{restriction.reason || 'Причина не указана'}</strong>
                                                        <span>До: {formatDateShort(restriction.until)}</span>
                                                    </div>
                                                ) : (
                                                    <span className="admin-muted-cell">Нет ограничений</span>
                                                )}
                                            </td>
                                            <td>
                                                <span className="admin-role-cell">
                                                    {item.is_super_admin ? 'Root' : item.is_admin ? 'Admin' : 'User'}
                                                </span>
                                            </td>
                                            <td>
                                                <span>{formatNumber(item.mind_count)} minds</span>
                                                <span>{formatNumber(item.chat_count)} sessions</span>
                                            </td>
                                            <td>{formatDate(item.created_at)}</td>
                                            <td>
                                                <div className="admin-action-row">
                                                    <button
                                                        type="button"
                                                        title={item.is_banned ? 'Разбанить' : 'Забанить'}
                                                        disabled={busyId === `user-${item.id}-is_banned` || item.is_super_admin}
                                                        onClick={() => (
                                                            item.is_banned
                                                                ? void clearUserRestriction(item, 'is_banned')
                                                                : openRestrictionDraft(item, 'is_banned')
                                                        )}
                                                    >
                                                        {item.is_banned ? <Unlock size={15} /> : <Ban size={15} />}
                                                    </button>
                                                    <button
                                                        type="button"
                                                        title={item.is_blocked ? 'Разблокировать' : 'Заблокировать'}
                                                        disabled={busyId === `user-${item.id}-is_blocked` || item.is_super_admin}
                                                        onClick={() => (
                                                            item.is_blocked
                                                                ? void clearUserRestriction(item, 'is_blocked')
                                                                : openRestrictionDraft(item, 'is_blocked')
                                                        )}
                                                    >
                                                        {item.is_blocked ? <Unlock size={15} /> : <Lock size={15} />}
                                                    </button>
                                                    <button
                                                        type="button"
                                                        title={item.is_admin ? 'Снять админа' : 'Назначить админа'}
                                                        disabled={!canAssignAdmins || item.is_super_admin || busyId === `user-${item.id}-admin`}
                                                        onClick={() => void updateAdminRole(item)}
                                                    >
                                                        <ShieldPlus size={15} />
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                    {users.length === 0 && !loading && <div className="admin-empty">Ничего не найдено</div>}
                    <PaginationControls
                        disabled={loading}
                        pagination={userPagination}
                        onPageChange={(page) => void loadUsers(page)}
                    />
                </div>
            )}

            {activeTab === 'minds' && (
                <div className="admin-section">
                    <div className="admin-controls">
                        <div className="admin-search">
                            <Search size={18} />
                            <input
                                value={mindQuery}
                                onChange={(event) => setMindQuery(event.target.value)}
                                placeholder="Поиск по mind, public id или автору"
                                maxLength={100}
                            />
                        </div>
                        <div className="admin-filter-row">
                            {MIND_STATUS_OPTIONS.map((option) => (
                                <button
                                    key={option.id}
                                    type="button"
                                    className={cn(mindStatusFilter === option.id && 'active')}
                                    onClick={() => setMindStatusFilter(option.id)}
                                >
                                    {option.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div className="admin-table-wrap">
                        <table className="admin-table">
                            <thead>
                                <tr>
                                    <th>Mind</th>
                                    <th>Автор</th>
                                    <th>Публикация</th>
                                    <th>Статус</th>
                                    <th>Обновлен</th>
                                    <th>Действия</th>
                                </tr>
                            </thead>
                            <tbody>
                                {minds.map((item) => (
                                    <tr key={item.public_id}>
                                        <td>
                                            <strong>{item.name}</strong>
                                            <span>{item.description}</span>
                                        </td>
                                        <td>
                                            <strong>{item.owner?.username || 'system'}</strong>
                                            <span>{item.owner?.email || item.public_id}</span>
                                        </td>
                                        <td>
                                            <span>{item.visibility}</span>
                                            <span>{item.category}</span>
                                        </td>
                                        <td>
                                            <div className="admin-chip-group">
                                                {item.is_featured && <span className="admin-status-chip tone-accent">Main</span>}
                                                {item.is_verified && <span className="admin-status-chip tone-success">Verified</span>}
                                                {item.is_banned && <span className="admin-status-chip tone-danger">Ban</span>}
                                                {!item.is_featured && !item.is_verified && !item.is_banned && (
                                                    <span className="admin-status-chip tone-muted">Normal</span>
                                                )}
                                            </div>
                                        </td>
                                        <td>{formatDate(item.updated_at)}</td>
                                        <td>
                                            <div className="admin-action-row">
                                                <button
                                                    type="button"
                                                    title={item.is_featured ? 'Открепить с главной' : 'Закрепить на главной'}
                                                    disabled={
                                                        item.visibility !== 'store' ||
                                                        item.is_banned ||
                                                        busyId === `mind-${item.public_id}-is_featured`
                                                    }
                                                    onClick={() => void updateMindFlag(item, 'is_featured')}
                                                >
                                                    <Sparkles size={15} />
                                                </button>
                                                <button
                                                    type="button"
                                                    title={item.is_verified ? 'Снять verified' : 'Выдать verified'}
                                                    disabled={busyId === `mind-${item.public_id}-is_verified`}
                                                    onClick={() => void updateMindFlag(item, 'is_verified')}
                                                >
                                                    <BadgeCheck size={15} />
                                                </button>
                                                <button
                                                    type="button"
                                                    title={item.is_banned ? 'Разбанить mind' : 'Забанить mind'}
                                                    disabled={busyId === `mind-${item.public_id}-is_banned`}
                                                    onClick={() => void updateMindFlag(item, 'is_banned')}
                                                >
                                                    {item.is_banned ? <Unlock size={15} /> : <Ban size={15} />}
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    {minds.length === 0 && !loading && <div className="admin-empty">Ничего не найдено</div>}
                    <PaginationControls
                        disabled={loading}
                        pagination={mindPagination}
                        onPageChange={(page) => void loadMinds(page)}
                    />
                </div>
            )}

            {activeTab === 'server' && (
                <div className="admin-server-grid">
                    {serverRows.map((item) => (
                        <div className="admin-server-row" key={item.label}>
                            <span>{item.icon}</span>
                            <div>
                                <strong>{item.value}</strong>
                                <small>{item.label}</small>
                            </div>
                        </div>
                    ))}
                    <div className="admin-server-panel">
                        <h2>Process</h2>
                        <dl>
                            <div>
                                <dt>PID</dt>
                                <dd>{overview?.server.process.pid || '—'}</dd>
                            </div>
                            <div>
                                <dt>Python</dt>
                                <dd>
                                    {overview?.server.process.implementation || 'Python'} {overview?.server.process.python || '—'}
                                </dd>
                            </div>
                            <div>
                                <dt>Executable</dt>
                                <dd>{overview?.server.process.python_executable || '—'}</dd>
                            </div>
                            <div>
                                <dt>Load avg</dt>
                                <dd>{overview?.server.process.load_average?.map((value) => value.toFixed(2)).join(' / ') || '—'}</dd>
                            </div>
                            <div>
                                <dt>Platform</dt>
                                <dd>{overview?.server.process.platform || '—'}</dd>
                            </div>
                            <div>
                                <dt>Machine</dt>
                                <dd>{overview?.server.process.machine || '—'}</dd>
                            </div>
                            <div>
                                <dt>Working dir</dt>
                                <dd>{overview?.server.process.cwd || '—'}</dd>
                            </div>
                            <div>
                                <dt>Started</dt>
                                <dd>{formatDate(overview?.server.started_at)}</dd>
                            </div>
                        </dl>
                    </div>
                    <div className="admin-server-panel">
                        <h2>Runtime</h2>
                        <dl>
                            <div>
                                <dt>Environment</dt>
                                <dd>{overview?.server.process.env || '—'}</dd>
                            </div>
                            <div>
                                <dt>Debug</dt>
                                <dd>{overview?.server.process.debug ? 'on' : 'off'}</dd>
                            </div>
                            <div>
                                <dt>Database</dt>
                                <dd>
                                    {overview?.server.components.database.status || '—'}
                                    {overview?.server.components.database.engine
                                        ? ` · ${overview.server.components.database.engine}`
                                        : ''}
                                </dd>
                            </div>
                            <div>
                                <dt>Redis</dt>
                                <dd>{overview?.server.components.redis.status || '—'}</dd>
                            </div>
                        </dl>
                    </div>
                    <div className="admin-server-panel">
                        <h2>Storage</h2>
                        <div className="admin-storage-list">
                            {overview?.server.components.storage.map((item) => (
                                <div key={item.key}>
                                    {item.exists && item.writable ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                                    <span>{item.key}</span>
                                    <small>
                                        {item.path}
                                        {item.disk ? ` · free ${formatBytes(item.disk.free_bytes)}` : ''}
                                    </small>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </section>
    );
}
