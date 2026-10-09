import { useEffect, useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import type { KeyboardEvent, MouseEventHandler, PropsWithChildren, Ref } from 'react';
import { cn } from '../../utils/cn';

interface ModalShellProps extends PropsWithChildren {
    ariaDescribedBy?: string;
    ariaLabel?: string;
    ariaLabelledBy?: string;
    className?: string;
    contentClassName?: string;
    onBackdropClick?: MouseEventHandler<HTMLDivElement>;
    onEscapeKey?: () => void;
    onRequestClose?: () => void;
    overlayRef?: Ref<HTMLDivElement>;
    contentRef?: Ref<HTMLDivElement>;
}

const FOCUSABLE_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'textarea:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    '[tabindex]:not([tabindex="-1"])',
].join(',');

let openModalCount = 0;

const GHOST_MIN_OPEN_MS = 120;
const GHOST_MAX_LIFETIME_MS = 420;
const GHOST_STRIPPED_SELECTOR = 'iframe, video, audio, object, embed, script';

function prefersReducedMotion() {
    return typeof window.matchMedia === 'function'
        && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// Parents unmount modals instantly, so the exit is played on an inert, non-interactive
// snapshot of the last frame. Embedded documents, media, scripts, ids and inline
// handlers are stripped so the snapshot can never load, run or be targeted.
function playExitGhost(overlay: HTMLElement) {
    if (!overlay.isConnected || prefersReducedMotion()) return;

    const ghost = overlay.cloneNode(true) as HTMLElement;
    const sourceNodes = [overlay, ...Array.from(overlay.querySelectorAll<HTMLElement>('*'))];
    const ghostNodes = [ghost, ...Array.from(ghost.querySelectorAll<HTMLElement>('*'))];
    const scrollOffsets = sourceNodes
        .map((node, index) => ({ index, top: node.scrollTop, left: node.scrollLeft }))
        .filter(({ top, left }) => top > 0 || left > 0);

    ghost.querySelectorAll(GHOST_STRIPPED_SELECTOR).forEach((node) => node.remove());
    ghostNodes.forEach((node) => {
        node.removeAttribute('id');
        Array.from(node.attributes).forEach(({ name }) => {
            if (name.toLowerCase().startsWith('on')) node.removeAttribute(name);
        });
    });
    ghost.setAttribute('aria-hidden', 'true');
    ghost.inert = true;
    ghost.classList.add('ui-modal-ghost');

    document.body.appendChild(ghost);
    scrollOffsets.forEach(({ index, top, left }) => {
        const node = ghostNodes[index];
        if (node?.isConnected) {
            node.scrollTop = top;
            node.scrollLeft = left;
        }
    });

    const removeGhost = () => ghost.remove();
    ghost.addEventListener('animationend', (event) => {
        if (event.target === ghost) removeGhost();
    });
    window.setTimeout(removeGhost, GHOST_MAX_LIFETIME_MS);
}

function assignRef<T>(ref: Ref<T> | undefined, value: T | null) {
    if (!ref) return;
    if (typeof ref === 'function') {
        ref(value);
        return;
    }
    (ref as { current: T | null }).current = value;
}

const ModalShell = ({
    children,
    ariaDescribedBy,
    ariaLabel,
    ariaLabelledBy,
    className = '',
    contentClassName = '',
    onBackdropClick,
    onEscapeKey,
    onRequestClose,
    overlayRef,
    contentRef,
}: ModalShellProps) => {
    const internalContentRef = useRef<HTMLDivElement | null>(null);
    const internalOverlayRef = useRef<HTMLDivElement | null>(null);
    const previouslyFocusedRef = useRef<HTMLElement | null>(null);

    useLayoutEffect(() => {
        const openedAt = performance.now();
        const overlay = internalOverlayRef.current;
        return () => {
            // Skip the StrictMode remount probe and modals that close as they open.
            if (!overlay || performance.now() - openedAt < GHOST_MIN_OPEN_MS) return;
            playExitGhost(overlay);
        };
    }, []);

    useEffect(() => {
        openModalCount += 1;
        document.documentElement.classList.add('modal-open');
        document.body.classList.add('modal-open');
        previouslyFocusedRef.current = document.activeElement instanceof HTMLElement
            ? document.activeElement
            : null;

        const frame = window.requestAnimationFrame(() => {
            const content = internalContentRef.current;
            if (!content) return;

            const alreadyFocusedInside = content.contains(document.activeElement);
            if (alreadyFocusedInside) return;

            const focusTarget = content.querySelector<HTMLElement>(FOCUSABLE_SELECTOR) || content;
            focusTarget.focus({ preventScroll: true });
        });

        return () => {
            window.cancelAnimationFrame(frame);
            openModalCount = Math.max(0, openModalCount - 1);
            if (openModalCount === 0) {
                document.documentElement.classList.remove('modal-open');
                document.body.classList.remove('modal-open');
            }
            previouslyFocusedRef.current?.focus?.({ preventScroll: true });
        };
    }, []);

    const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
        if (event.key === 'Escape') {
            onEscapeKey?.();
            onRequestClose?.();
            return;
        }

        if (event.key !== 'Tab') {
            return;
        }

        const content = internalContentRef.current;
        if (!content) return;

        const focusable = Array.from(content.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
            .filter((element) => !element.hasAttribute('disabled') && element.getAttribute('aria-hidden') !== 'true');

        if (focusable.length === 0) {
            event.preventDefault();
            content.focus({ preventScroll: true });
            return;
        }

        const first = focusable[0]!;
        const last = focusable[focusable.length - 1]!;

        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    };

    return createPortal(
        <div
            ref={(node) => {
                internalOverlayRef.current = node;
                assignRef(overlayRef, node);
            }}
            className={cn(
                'ui-modal-overlay overflow-y-auto backdrop-blur-[2px]',
                className
            )}
            onClick={onBackdropClick}
            onKeyDown={handleKeyDown}
        >
            <div
                ref={(node) => {
                    internalContentRef.current = node;
                    assignRef(contentRef, node);
                }}
                className={cn(
                    'ui-modal-card relative overflow-hidden',
                    contentClassName
                )}
                role="dialog"
                aria-modal="true"
                aria-label={ariaLabel}
                aria-labelledby={ariaLabelledBy}
                aria-describedby={ariaDescribedBy}
                tabIndex={-1}
                onClick={(event) => event.stopPropagation()}
            >
                {children}
            </div>
        </div>,
        document.body
    );
};

export default ModalShell;
