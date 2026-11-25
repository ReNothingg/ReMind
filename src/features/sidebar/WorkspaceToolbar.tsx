import { useLayoutEffect, useRef, useState } from 'react';
import { Check, FolderPlus, Search, SlidersHorizontal, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import SidebarMenu from './SidebarMenu';
import type { RailGrouping, RailOrder, RailSource } from './railPreferences';

function ViewGroup<T extends string>({ label, options, value, onSelect }: {
  label: string;
  options: Array<[T, string]>;
  value: T;
  onSelect: (value: T) => void;
}) {
  return (
    <div className="sidebar-menu-group" role="group" aria-label={label}>
      <div className="sidebar-menu-heading" aria-hidden="true">{label}</div>
      {options.map(([id, title]) => (
        <button key={id} type="button" role="menuitemradio" aria-checked={id === value}
          className="sidebar-menu-item sidebar-menu-radio" onClick={() => onSelect(id)}>
          <span>{title}</span>
          {id === value && <Check size={15} aria-hidden="true" />}
        </button>
      ))}
    </div>
  );
}

export default function WorkspaceToolbar({
  wide, searching, query, grouping, order, source, onSearch, onSearchClose, onQuery,
  onGrouping, onOrder, onSource, onAddProject,
}: {
  wide: boolean;
  searching: boolean;
  query: string;
  grouping: RailGrouping;
  order: RailOrder;
  source: RailSource;
  onSearch: () => void;
  onSearchClose: () => void;
  onQuery: (query: string) => void;
  onGrouping: (value: RailGrouping) => void;
  onOrder: (value: RailOrder) => void;
  onSource: (value: RailSource) => void;
  onAddProject: () => void;
}) {
  const { t } = useTranslation();
  const [view, setView] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const search = useRef<HTMLButtonElement>(null);
  const previousSearch = useRef(false);

  useLayoutEffect(() => {
    if (wide && searching) input.current?.focus({ preventScroll: true });
    else if (wide && previousSearch.current) search.current?.focus({ preventScroll: true });
    previousSearch.current = searching;
  }, [searching, wide]);

  if (wide && searching) return (
    <div className="sidebar-workspace-search" role="search">
      <Search size={16} aria-hidden="true" />
      <input ref={input} type="search" maxLength={120} value={query} aria-label={t('rail.searchInput')}
        placeholder={t('rail.sidebar.searchPlaceholder')}
        onChange={(event) => onQuery(event.target.value.replaceAll('\u0000', ''))}
        onKeyDown={(event) => {
          if (event.key !== 'Escape') return;
          event.stopPropagation();
          onSearchClose();
        }} />
      <button type="button" className="sidebar-icon-button" onClick={onSearchClose} aria-label={t('rail.sidebar.closeSearch')}>
        <X size={17} aria-hidden="true" />
      </button>
    </div>
  );

  return (
    <div className="sidebar-workspace-bar">
      {wide && <h2>{t(grouping === 'flat' ? 'rail.yourChats' : 'projects.title')}</h2>}
      <button ref={search} type="button" className="sidebar-icon-button" onClick={onSearch}
        aria-label={t('rail.searchInput')} aria-keyshortcuts="Control+Alt+K Meta+Alt+K" title={t('rail.searchInput')}>
        <Search size={17} aria-hidden="true" />
      </button>
      {wide && (
        <SidebarMenu label={t('rail.sidebar.view')} open={view} onOpenChange={setView}
          icon={<SlidersHorizontal size={17} />} emphasized={source !== 'all' || grouping !== 'projects' || order !== 'recent'}>
          <ViewGroup label={t('rail.sidebar.group')} value={grouping} onSelect={onGrouping}
            options={[[ 'projects', t('projects.title') ], [ 'flat', t('rail.sidebar.flat') ]]} />
          <ViewGroup label={t('rail.sidebar.order')} value={order} onSelect={onOrder}
            options={[[ 'recent', t('rail.sidebar.recent') ], [ 'alphabetical', t('rail.sidebar.alphabetical') ]]} />
          <ViewGroup label={t('rail.channelFilter.label')} value={source} onSelect={onSource}
            options={[[ 'all', t('rail.channelFilter.all') ], [ 'web', t('rail.channelFilter.web') ], [ 'telegram', t('rail.channelFilter.telegram') ]]} />
        </SidebarMenu>
      )}
      <button type="button" className="sidebar-icon-button" onClick={onAddProject} aria-label={t('projects.new')} title={t('projects.new')}>
        <FolderPlus size={17} aria-hidden="true" />
      </button>
    </div>
  );
}
