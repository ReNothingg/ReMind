import { useRef, useState, type ReactNode } from 'react';
import { Boxes, Pin, PinOff } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import SidebarMenu from './SidebarMenu';
import type { RailPanelId } from './railPreferences';

export type SidebarPanel = {
  id: RailPanelId;
  label: string;
  icon: ReactNode;
  active: boolean;
  open: () => void;
};

export default function SidebarPanels({ panels, unpinned, wide, onTogglePinned }: {
  panels: SidebarPanel[];
  unpinned: readonly RailPanelId[];
  wide: boolean;
  onTogglePinned: (id: RailPanelId) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const navigation = useRef<HTMLElement>(null);
  const pinned = panels.filter((panel) => !unpinned.includes(panel.id));

  return (
    <nav className="sidebar-panels" aria-label={t('rail.sidebar.sections')} ref={navigation}>
      {pinned.map((panel) => (
        <div className="sidebar-panel-row" key={panel.id}>
          <button
            type="button" className="sidebar-panel-button" aria-current={panel.active ? 'page' : undefined}
            aria-label={panel.label} title={panel.label} onClick={panel.open}
          >
            <span className="sidebar-glyph" aria-hidden="true">{panel.icon}</span>
            {wide && <span className="sidebar-panel-label">{panel.label}</span>}
          </button>
          {wide && (
            <button
              type="button" className="sidebar-panel-unpin sidebar-icon-button"
              aria-label={t('rail.sidebar.unpin', { name: panel.label })}
              title={t('rail.sidebar.unpin', { name: panel.label })}
              onClick={() => {
                navigation.current?.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')?.focus({ preventScroll: true });
                onTogglePinned(panel.id);
              }}
            >
              <PinOff size={15} aria-hidden="true" />
            </button>
          )}
        </div>
      ))}
      {panels.length > 0 && (
        <SidebarMenu
          label={t('rail.sidebar.more')} open={open} onOpenChange={setOpen}
          icon={<Boxes size={17} />} wide={wide} showLabel
          emphasized={panels.some((panel) => panel.active && unpinned.includes(panel.id))}
        >
          {panels.map((panel) => {
            const isPinned = !unpinned.includes(panel.id);
            return (
              <div className="sidebar-menu-panel" role="presentation" key={panel.id}>
                <button type="button" role="menuitem" className="sidebar-menu-item"
                  aria-current={panel.active ? 'page' : undefined}
                  onClick={() => { setOpen(false); panel.open(); }}>
                  <span className="sidebar-glyph" aria-hidden="true">{panel.icon}</span>
                  <span>{panel.label}</span>
                </button>
                <button type="button" role="menuitemcheckbox" aria-checked={isPinned} className="sidebar-menu-pin"
                  aria-label={t('rail.sidebar.pin', { name: panel.label })}
                  title={t(isPinned ? 'rail.sidebar.unpin' : 'rail.sidebar.pin', { name: panel.label })}
                  onClick={() => onTogglePinned(panel.id)}>
                  {isPinned ? <PinOff size={16} aria-hidden="true" /> : <Pin size={16} aria-hidden="true" />}
                </button>
              </div>
            );
          })}
        </SidebarMenu>
      )}
    </nav>
  );
}
