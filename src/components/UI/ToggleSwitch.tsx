import { cn } from '../../utils/cn';

const ToggleSwitch = ({
  checked,
  onClick,
  disabled = false,
  className = '',
  ariaLabel
}) => {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'relative inline-flex h-11 w-12 shrink-0 items-center justify-center rounded-md border-0 bg-transparent p-0 outline-none transition duration-200 ease-out',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-border-focus)]',
        'disabled:cursor-not-allowed disabled:opacity-60',
        className
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          'relative inline-flex h-6 w-11 items-center rounded-full border transition duration-200 ease-out',
          checked
            ? 'border-accent-brand bg-accent-brand'
            : 'border-border-strong bg-interactive'
        )}
      >
        <span
          className={cn(
            'pointer-events-none absolute left-0.5 top-0.5 size-[18px] rounded-full transition-transform duration-200 ease-out',
            checked
              ? 'translate-x-5 bg-[var(--color-text-on-accent-bg)]'
              : 'bg-[var(--color-toggle-thumb)]'
          )}
        />
      </span>
    </button>
  );
};

export default ToggleSwitch;
