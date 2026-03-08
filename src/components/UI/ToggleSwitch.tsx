import React from 'react';
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
        'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border outline-none transition duration-200 ease-out',
        'focus-visible:ring-2 focus-visible:ring-[rgba(var(--color-accent-raw),0.28)] focus-visible:ring-offset-2 focus-visible:ring-offset-surface',
        'disabled:cursor-not-allowed disabled:opacity-60',
        "after:pointer-events-none after:absolute after:left-0.5 after:top-0.5 after:size-[18px] after:rounded-full after:bg-white after:shadow-sm after:transition-transform after:duration-200 after:ease-out after:content-['']",
        checked
          ? 'border-accent-brand bg-accent-brand after:translate-x-5'
          : 'border-border-strong bg-interactive hover:border-border-heavy hover:bg-surface-alt',
        className
      )}
    />
  );
};

export default ToggleSwitch;
