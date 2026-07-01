import { useEffect, useRef } from 'react';
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
    const previouslyFocusedRef = useRef<HTMLElement | null>(null);

    useEffect(() => {
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

    return (
        <div
            ref={(node) => {
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
        </div>
    );
};

export default ModalShell;
