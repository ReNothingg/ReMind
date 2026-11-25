import { useId, useLayoutEffect, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '../../utils/cn';

function menuItems(panel: HTMLDivElement | null) {
  return Array.from(panel?.querySelectorAll<HTMLButtonElement>('button[role^="menuitem"]:not(:disabled)') || []);
}

export default function SidebarMenu({
  label, open, onOpenChange, icon, children, wide = true, showLabel = false, emphasized = false,
}: {
  label: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  icon: ReactNode;
  children: ReactNode;
  wide?: boolean;
  showLabel?: boolean;
  emphasized?: boolean;
}) {
  const id = useId();
  const anchor = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const edge = useRef<'first' | 'last'>('first');

  useLayoutEffect(() => {
    if (!open || !menu.current || !anchor.current) return;
    const panel = menu.current;
    const trigger = anchor.current;
    function place() {
      const bounds = trigger.getBoundingClientRect();
      const rail = trigger.closest('#appRail')?.getBoundingClientRect() ?? bounds;
      const rtl = getComputedStyle(trigger).direction === 'rtl';
      const inline = wide ? (rtl ? bounds.right - panel.offsetWidth : bounds.left)
        : rtl ? rail.left - panel.offsetWidth - 6 : rail.right + 6;
      const preferredTop = wide ? bounds.bottom + 6 : bounds.top;
      const block = !wide || preferredTop + panel.offsetHeight <= window.innerHeight - 8
        ? preferredTop : bounds.top - panel.offsetHeight - 6;
      panel.style.left = `${Math.max(8, Math.min(window.innerWidth - panel.offsetWidth - 8, inline))}px`;
      panel.style.top = `${Math.max(8, Math.min(window.innerHeight - panel.offsetHeight - 8, block))}px`;
      panel.style.direction = rtl ? 'rtl' : 'ltr';
    }
    place();
    const rows = menuItems(panel);
    (edge.current === 'last' ? rows.at(-1) : rows[0])?.focus({ preventScroll: true });
    function dismiss(event: PointerEvent) {
      const target = event.target as Node | null;
      if (target && !trigger.contains(target) && !panel.contains(target)) onOpenChange(false);
    }
    window.addEventListener('resize', place);
    document.addEventListener('scroll', place, true);
    document.addEventListener('pointerdown', dismiss);
    return () => {
      window.removeEventListener('resize', place);
      document.removeEventListener('scroll', place, true);
      document.removeEventListener('pointerdown', dismiss);
    };
  }, [open, onOpenChange, wide]);

  function handleMenuKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape' || event.key === 'Tab') {
      event.preventDefault();
      event.stopPropagation();
      onOpenChange(false);
      anchor.current?.focus({ preventScroll: true });
      return;
    }
    const rows = menuItems(menu.current);
    if (!rows.length) return;
    const current = rows.indexOf(document.activeElement as HTMLButtonElement);
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? rows.length - 1
      : event.key === 'ArrowDown' ? (current + 1) % rows.length
        : event.key === 'ArrowUp' ? (current + rows.length - 1) % rows.length : -1;
    if (index < 0) return;
    event.preventDefault();
    rows[index]?.focus();
  }

  return (
    <>
      <button
        ref={anchor}
        type="button"
        className={cn(showLabel ? 'sidebar-panel-button' : 'sidebar-icon-button', emphasized && 'is-emphasized')}
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => { edge.current = 'first'; onOpenChange(!open); }}
        onKeyDown={(event) => {
          if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
          event.preventDefault();
          edge.current = event.key === 'ArrowUp' ? 'last' : 'first';
          onOpenChange(true);
        }}
      >
        <span className="sidebar-glyph" aria-hidden="true">{icon}</span>
        {showLabel && wide && <span className="sidebar-panel-label">{label}</span>}
      </button>
      {open && createPortal(
        <div className="sidebar-floating-menu" id={id} ref={menu} role="menu" aria-label={label} onKeyDown={handleMenuKey}>
          {children}
        </div>,
        document.body
      )}
    </>
  );
}
