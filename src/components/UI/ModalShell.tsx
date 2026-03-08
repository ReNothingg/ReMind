import type { MouseEventHandler, PropsWithChildren, Ref } from 'react';
import { cn } from '../../utils/cn';

interface ModalShellProps extends PropsWithChildren {
    className?: string;
    contentClassName?: string;
    onBackdropClick?: MouseEventHandler<HTMLDivElement>;
    overlayRef?: Ref<HTMLDivElement>;
    contentRef?: Ref<HTMLDivElement>;
}

const ModalShell = ({
    children,
    className = '',
    contentClassName = '',
    onBackdropClick,
    overlayRef,
    contentRef,
}: ModalShellProps) => {
    return (
        <div
            ref={overlayRef}
            className={cn(
                'ui-modal-overlay overflow-y-auto backdrop-blur-[2px]',
                className
            )}
            onClick={onBackdropClick}
        >
            <div
                ref={contentRef}
                className={cn(
                    'ui-modal-card relative overflow-hidden',
                    contentClassName
                )}
                onClick={(event) => event.stopPropagation()}
            >
                {children}
            </div>
        </div>
    );
};

export default ModalShell;
