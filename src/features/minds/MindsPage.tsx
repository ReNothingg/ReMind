import { useCallback, useEffect, useMemo, useState, useDeferredValue } from 'react';
import { useTranslation } from 'react-i18next';
import {
    BadgeCheck,
    BrainCircuit,
    Edit3,
    ExternalLink,
    Pin,
    PinOff,
    Plus,
    Search,
    ShieldCheck,
    Trash2,
} from 'lucide-react';
import { apiService, type Mind, type MindCategory } from '../../services/api';
import { cn } from '../../utils/cn';
import { getMindErrorMessage } from './errorMessages';

type MindsPageProps = {
    isAuthenticated: boolean;
    onCreateMind: () => void;
    onEditMind: (mind: Mind) => void;
    onOpenAuth: () => void;
    onPinnedChange?: () => void;
    onStartMind: (mind: Mind) => void;
};

const FALLBACK_CATEGORIES: MindCategory[] = [
    { id: 'all', label: 'all' },
    { id: 'general', label: 'general' },
    { id: 'education', label: 'education' },
    { id: 'development', label: 'development' },
    { id: 'productivity', label: 'productivity' },
    { id: 'creative', label: 'creative' },
    { id: 'business', label: 'business' },
    { id: 'security', label: 'security' },
];

type Translate = ReturnType<typeof useTranslation>['t'];

function categoryLabel(t: Translate, categories: MindCategory[], categoryId: string): string {
    const fallbackLabel = categories.find((category) => category.id === categoryId)?.label || categoryId;
    return t(`minds.categories.${categoryId}`, { defaultValue: fallbackLabel });
}

function visibilityLabel(t: Translate, visibility: Mind['visibility']): string {
    if (visibility === 'private') return t('minds.visibility.private');
    if (visibility === 'link') return t('minds.visibility.link');
    return t('minds.visibility.store');
}

function useMindErrorMessages() {
    const { t } = useTranslation();
    return useMemo(
        () => ({
            authRequired: t('minds.errors.authRequired'),
            accessDenied: t('minds.errors.accessDenied'),
            notFound: t('minds.errors.notFound'),
            rateLimited: t('minds.errors.rateLimited'),
        }),
        [t]
    );
}

function MindCard({
    categories,
    isAuthenticated,
    mind,
    onEdit,
    onOpenAuth,
    onPinToggle,
    onStart,
}: {
    categories: MindCategory[];
    isAuthenticated: boolean;
    mind: Mind;
    onEdit?: (mind: Mind) => void;
    onOpenAuth: () => void;
    onPinToggle: (mind: Mind) => Promise<void>;
    onStart: (mind: Mind) => void;
}) {
    const { t } = useTranslation();

    return (
        <article className="mind-card">
            <div className="mind-card-header">
                <div className="mind-avatar" aria-hidden="true">
                    <BrainCircuit size={22} />
                </div>
                <div className="mind-card-title-group">
                    <div className="mind-card-title-row">
                        <h3>{mind.name}</h3>
                        {mind.is_verified && (
                            <span className="mind-verified" title={t('minds.verified')}>
                                <BadgeCheck size={16} />
                            </span>
                        )}
                    </div>
                    <span>{categoryLabel(t, categories, mind.category)}</span>
                </div>
            </div>

            <p className="mind-description">{mind.description}</p>

            {mind.starters.length > 0 && (
                <div className="mind-starters" aria-label={t('minds.startersAria')}>
                    {mind.starters.slice(0, 3).map((starter) => (
                        <button key={starter} type="button" onClick={() => onStart(mind)}>
                            {starter}
                        </button>
                    ))}
                </div>
            )}

            <div className="mind-card-footer">
                <button type="button" className="mind-primary-action" onClick={() => onStart(mind)}>
                    <ExternalLink size={16} />
                    {t('minds.openChat')}
                </button>
                <button
                    type="button"
                    className={cn('mind-icon-action', mind.is_pinned && 'active')}
                    title={mind.is_pinned ? t('minds.unpinTitle') : t('minds.pinTitle')}
                    aria-label={mind.is_pinned ? t('minds.unpinAria') : t('minds.pinAria')}
                    onClick={() => {
                        if (!isAuthenticated) {
                            onOpenAuth();
                            return;
                        }
                        void onPinToggle(mind);
                    }}
                >
                    {mind.is_pinned ? <PinOff size={16} /> : <Pin size={16} />}
                </button>
                {mind.can_edit && onEdit && (
                    <button
                        type="button"
                        className="mind-icon-action"
                        title={t('minds.edit')}
                        aria-label={t('minds.editAria')}
                        onClick={() => onEdit(mind)}
                    >
                        <Edit3 size={16} />
                    </button>
                )}
            </div>
        </article>
    );
}

export default function MindsPage({
    isAuthenticated,
    onCreateMind,
    onEditMind,
    onOpenAuth,
    onPinnedChange,
    onStartMind,
}: MindsPageProps) {
    const { t } = useTranslation();
    const mindErrorMessages = useMindErrorMessages();
    const [categories, setCategories] = useState<MindCategory[]>(FALLBACK_CATEGORIES);
    const [activeCategory, setActiveCategory] = useState('all');
    const [activeTab, setActiveTab] = useState<'store' | 'mine'>('store');
    const [searchQuery, setSearchQuery] = useState('');
    const [storeMinds, setStoreMinds] = useState<Mind[]>([]);
    const [myMinds, setMyMinds] = useState<Mind[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const deferredSearch = useDeferredValue(searchQuery.trim());

    const categoryTabs = useMemo(() => {
        const normalized = categories.some((category) => category.id === 'all')
            ? categories
            : [{ id: 'all', label: 'all' }, ...categories];
        return normalized;
    }, [categories]);

    const loadMinds = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            const categoryParams = activeCategory === 'all' ? {} : { category: activeCategory };
            const [categoryList, storeResponse, mineResponse] = await Promise.all([
                apiService.listMindCategories(),
                apiService.listMinds({ ...categoryParams, q: deferredSearch, limit: 80 }),
                isAuthenticated
                    ? apiService.listMinds({ ...categoryParams, q: deferredSearch, mine: true, limit: 80 })
                    : Promise.resolve({ minds: [] }),
            ]);

            if (categoryList.length > 0) {
                setCategories([{ id: 'all', label: 'all' }, ...categoryList]);
            }
            setStoreMinds(storeResponse.minds || []);
            setMyMinds(mineResponse.minds || []);
        } catch (loadError) {
            console.error('Failed to load minds', loadError);
            setError(getMindErrorMessage(loadError, t('minds.errors.load'), mindErrorMessages));
        } finally {
            setLoading(false);
        }
    }, [activeCategory, deferredSearch, isAuthenticated, mindErrorMessages, t]);

    useEffect(() => {
        void loadMinds();
    }, [loadMinds]);

    const updateMindInLists = useCallback((updatedMind: Mind) => {
        setStoreMinds((current) =>
            current.map((mind) => (mind.public_id === updatedMind.public_id ? updatedMind : mind))
        );
        setMyMinds((current) =>
            current.map((mind) => (mind.public_id === updatedMind.public_id ? updatedMind : mind))
        );
    }, []);

    const handlePinToggle = useCallback(
        async (mind: Mind) => {
            try {
                const updatedMind = await apiService.setMindPinned(mind.public_id, !mind.is_pinned);
                if (updatedMind) {
                    updateMindInLists(updatedMind);
                }
                onPinnedChange?.();
            } catch (pinError) {
                console.error('Failed to update mind pin', pinError);
                setError(getMindErrorMessage(pinError, t('minds.errors.pin'), mindErrorMessages));
            }
        },
        [mindErrorMessages, onPinnedChange, t, updateMindInLists]
    );

    const handleDeleteMind = useCallback(
        async (mind: Mind) => {
            if (!mind.can_edit) return;
            const confirmed = window.confirm(t('minds.confirmDelete', { name: mind.name }));
            if (!confirmed) return;

            try {
                await apiService.deleteMind(mind.public_id);
                setMyMinds((current) => current.filter((item) => item.public_id !== mind.public_id));
                setStoreMinds((current) => current.filter((item) => item.public_id !== mind.public_id));
                onPinnedChange?.();
            } catch (deleteError) {
                console.error('Failed to delete mind', deleteError);
                setError(getMindErrorMessage(deleteError, t('minds.errors.delete'), mindErrorMessages));
            }
        },
        [mindErrorMessages, onPinnedChange, t]
    );

    const visibleMinds = activeTab === 'store' ? storeMinds : myMinds;

    return (
        <section className="minds-page">
            <div className="minds-toolbar">
                <div>
                    <div className="minds-title-row">
                        <BrainCircuit size={30} />
                        <h1>Minds</h1>
                    </div>
                    <p>{t('minds.subtitle')}</p>
                </div>
                <button
                    type="button"
                    className="mind-create-button"
                    onClick={isAuthenticated ? onCreateMind : onOpenAuth}
                >
                    <Plus size={18} />
                    {t('minds.create')}
                </button>
            </div>

            <div className="minds-controls">
                <div className="minds-search">
                    <Search size={18} />
                    <input
                        value={searchQuery}
                        onChange={(event) => setSearchQuery(event.target.value)}
                        placeholder={t('minds.searchPlaceholder')}
                        aria-label={t('minds.searchAria')}
                        maxLength={80}
                    />
                </div>
                <div className="minds-tabs" role="tablist" aria-label={t('minds.tabsAria')}>
                    <button
                        type="button"
                        className={cn(activeTab === 'store' && 'active')}
                        onClick={() => setActiveTab('store')}
                    >
                        {t('minds.tabs.store')}
                    </button>
                    <button
                        type="button"
                        className={cn(activeTab === 'mine' && 'active')}
                        onClick={() => {
                            if (!isAuthenticated) {
                                onOpenAuth();
                                return;
                            }
                            setActiveTab('mine');
                        }}
                    >
                        {t('minds.tabs.mine')}
                    </button>
                </div>
            </div>

            <div className="mind-category-tabs" aria-label={t('minds.categoriesAria')}>
                {categoryTabs.map((category) => (
                    <button
                        key={category.id}
                        type="button"
                        className={cn(activeCategory === category.id && 'active')}
                        onClick={() => setActiveCategory(category.id)}
                    >
                        {categoryLabel(t, categories, category.id)}
                    </button>
                ))}
            </div>

            {error && <div className="mind-error">{error}</div>}

            {loading ? (
                <div className="mind-empty-state">{t('minds.loading')}</div>
            ) : visibleMinds.length === 0 ? (
                <div className="mind-empty-state">
                    <ShieldCheck size={24} />
                    {activeTab === 'mine'
                        ? t('minds.emptyMine')
                        : t('minds.emptyStore')}
                </div>
            ) : (
                <div className="minds-grid">
                    {visibleMinds.map((mind) => (
                        <div key={mind.public_id} className="mind-card-wrap">
                            <MindCard
                                categories={categories}
                                isAuthenticated={isAuthenticated}
                                mind={mind}
                                onEdit={onEditMind}
                                onOpenAuth={onOpenAuth}
                                onPinToggle={handlePinToggle}
                                onStart={onStartMind}
                            />

                            {activeTab === 'mine' && (
                                <div className="mind-management-row">
                                    <span>{visibilityLabel(t, mind.visibility)}</span>
                                    <div>
                                        <button type="button" onClick={() => onEditMind(mind)}>
                                            <Edit3 size={15} />
                                            {t('minds.edit')}
                                        </button>
                                        <button
                                            type="button"
                                            className="danger"
                                            onClick={() => void handleDeleteMind(mind)}
                                        >
                                            <Trash2 size={15} />
                                            {t('minds.delete')}
                                        </button>
                                    </div>
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </section>
    );
}
