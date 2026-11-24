import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';
import ModalShell from '../../components/UI/ModalShell';
import { cn } from '../../utils/cn';
import type { SettingsSection, SettingsSectionGroup, SettingsSectionId } from './settingsSections';

export default function SettingsShell({
  title, closeLabel, backLabel, groups, active, compact, onSelect, onBack, onClose, children,
}: {
  title: string;
  closeLabel: string;
  backLabel: string;
  groups: SettingsSectionGroup[];
  active?: SettingsSection;
  compact: boolean;
  onSelect: (id: SettingsSectionId) => void;
  onBack: () => void;
  onClose: () => void;
  children: ReactNode;
}) {
  const titleId = useId();
  const pageTitleId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const navigation = useRef<HTMLElement>(null);
  const previous = useRef<SettingsSectionId | undefined>(undefined);
  const rows = groups.flatMap((group) => group.rows);
  const indexVisible = !compact || !active;
  const activeId = active?.id;

  useEffect(() => {
    const previousId = previous.current;
    previous.current = activeId;
    if (!compact) return;
    const frame = window.requestAnimationFrame(() => {
      if (activeId) heading.current?.focus({ preventScroll: true });
      else if (previousId) navigation.current?.querySelector<HTMLElement>(`[data-settings-tab="${previousId}"]`)?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeId, compact]);

  const handleTabsKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    const current = rows.findIndex((row) => row.id === activeId);
    const last = rows.length - 1;
    const positions: Record<string, number | undefined> = {
      ArrowDown: (current + 1) % rows.length,
      ArrowUp: (current + last) % rows.length,
      Home: 0,
      End: last,
    };
    const next = positions[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const row = rows[next];
    if (!row) return;
    onSelect(row.id);
    navigation.current?.querySelector<HTMLElement>(`[data-settings-tab="${row.id}"]`)?.focus();
  };

  const closeButton = (
    <button className="settings-shell-action" type="button" onClick={onClose} aria-label={closeLabel}>
      <X size={19} strokeWidth={1.8} aria-hidden="true" />
    </button>
  );

  return (
    <ModalShell
      ariaLabelledBy={compact && active ? pageTitleId : titleId}
      className="user-settings-modal active"
      contentClassName={cn('user-settings-content settings-shell', compact && 'is-compact', compact && active && 'is-section')}
      onBackdropClick={onClose}
      onRequestClose={onClose}
    >
      {indexVisible && (
        <div className="settings-shell-title">
          <h2 id={titleId}>{title}</h2>
          {compact && closeButton}
        </div>
      )}
      {indexVisible && (
        <nav className="settings-tabs ui-scrollbar-thin" ref={navigation}
          role={compact ? undefined : 'tablist'} aria-label={title}
          aria-orientation={compact ? undefined : 'vertical'}
          onKeyDown={compact ? undefined : handleTabsKeyDown}>
          {groups.map((group) => (
            <div className="settings-nav-group" role={compact ? undefined : 'presentation'} key={group.id}>
              {group.label && <span className="settings-nav-heading">{group.label}</span>}
              {group.rows.map((row) => (
                <button key={row.id} type="button" className={cn('settings-tab', row.id === activeId && 'active')}
                  role={compact ? undefined : 'tab'} aria-selected={compact ? undefined : row.id === activeId}
                  aria-controls={!compact && row.id === activeId ? 'settings-panel-' + row.id : undefined}
                  id={'settings-tab-' + row.id} data-settings-tab={row.id}
                  tabIndex={compact || row.id === activeId ? 0 : -1}
                  onFocus={(event) => event.currentTarget.scrollIntoView({ block: 'nearest', inline: 'nearest' })}
                  onClick={() => onSelect(row.id)}>
                  <span className="settings-tab-icon" aria-hidden="true"><row.icon size={17} /></span>
                  <span className="settings-tab-label">{row.label}</span>
                  {compact && <ChevronRight className="settings-nav-arrow" size={17} aria-hidden="true" />}
                </button>
              ))}
            </div>
          ))}
        </nav>
      )}
      {active && (
        <>
          <header className="settings-shell-header">
            {compact && (
              <button className="settings-shell-action settings-shell-back" type="button" onClick={onBack} aria-label={backLabel}>
                <ChevronLeft size={21} strokeWidth={1.8} aria-hidden="true" />
              </button>
            )}
            <h2 id={pageTitleId} ref={heading} tabIndex={-1}>{active.label}</h2>
            {closeButton}
          </header>
          <div className="settings-content" role={compact ? undefined : 'tabpanel'}
            id={'settings-panel-' + active.id} aria-labelledby={compact ? pageTitleId : 'settings-tab-' + active.id}>
            {children}
          </div>
        </>
      )}
    </ModalShell>
  );
}
