import type { ReactNode } from 'react';

type SocialAuthButtonProps = {
    children: ReactNode;
    icon: ReactNode;
    label: string;
    href?: string;
    onClick?: () => void;
    disabled?: boolean;
    busy?: boolean;
    newWindow?: boolean;
};

const sharedClassName = 'flex min-h-11 w-full items-center justify-center gap-2 rounded-md border border-border-strong bg-surface px-4 py-2.5 text-[0.94rem] font-medium text-foreground transition-colors duration-200 hover:border-border-heavy hover:bg-interactive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface disabled:cursor-wait disabled:opacity-70';

export const TelegramLogo = () => (
    <svg viewBox="0 0 24 24" className="size-5 text-[#229ed9]" aria-hidden="true">
        <path
            fill="currentColor"
            d="M21.6 3.2 18.7 20c-.2 1.2-.8 1.5-1.8.9l-4.4-3.2-2.1 2c-.2.2-.4.4-.9.4l.3-4.5 8.2-7.4c.4-.3-.1-.5-.5-.2L7.4 14.4 3 13c-1.2-.4-1.2-1.2.2-1.7L20.3 2.7c.8-.3 1.5.2 1.3.5Z"
        />
    </svg>
);

export const GoogleLogo = () => (
    <svg viewBox="0 0 24 24" className="size-5" aria-hidden="true">
        <path fill="#4285F4" d="M21.6 12.2c0-.7-.1-1.5-.2-2.2H12v4.2h5.4a4.6 4.6 0 0 1-2 3v2.7h3.5c2-1.9 3.2-4.6 3.2-7.7Z" />
        <path fill="#34A853" d="M12 22c2.9 0 5.3-.9 7-2.6l-3.4-2.7c-1 .7-2.2 1-3.6 1a6.2 6.2 0 0 1-5.8-4.3H2.7v2.8A10 10 0 0 0 12 22Z" />
        <path fill="#FBBC05" d="M6.2 13.4a6 6 0 0 1 0-3.8V6.8H2.7a10 10 0 0 0 0 9.4l3.5-2.8Z" />
        <path fill="#EA4335" d="M12 6.2c1.6 0 3 .5 4.1 1.6l3.1-3.1A10 10 0 0 0 2.7 6.8l3.5 2.8A6.2 6.2 0 0 1 12 6.2Z" />
    </svg>
);

const SocialAuthButton = ({
    children,
    icon,
    label,
    href,
    onClick,
    disabled = false,
    busy = false,
    newWindow = false,
}: SocialAuthButtonProps) => {
    if (href && !disabled) {
        return (
            <a
                className={sharedClassName}
                href={href}
                onClick={onClick}
                target={newWindow ? '_blank' : undefined}
                rel={newWindow ? 'noopener noreferrer' : undefined}
                aria-label={label}
            >
                {icon}
                <span>{children}</span>
            </a>
        );
    }

    return (
        <button
            type="button"
            className={sharedClassName}
            onClick={onClick}
            disabled={disabled}
            aria-busy={busy}
            aria-label={label}
        >
            {icon}
            <span>{children}</span>
        </button>
    );
};

export default SocialAuthButton;
