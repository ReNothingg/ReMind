import { useState, useRef, useEffect, useLayoutEffect, useId } from 'react';
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../utils/cn';

type SelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

type CustomSelectProps = {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  label?: string;
  disabled?: boolean;
  className?: string;
  placeholder?: string;
};

const CustomSelect = ({
  value,
  onChange,
  options,
  label,
  disabled = false,
  className = '',
  placeholder
}: CustomSelectProps) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const [dropDirection, setDropDirection] = useState<'down' | 'up'>('down');
  const [dropdownMaxHeight, setDropdownMaxHeight] = useState<number | null>(null);
  const selectId = useId();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dropdownRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const selectedOption = options.find(opt => opt.value === value);
  const displayText = selectedOption?.label || placeholder || t('common.selectOption');
  const labelId = `${selectId}-label`;
  const valueId = `${selectId}-value`;
  const listboxId = `${selectId}-listbox`;

  const selectedIndex = options.findIndex(opt => opt.value === value);
  const firstEnabledIndex = options.findIndex(opt => !opt.disabled);
  const activeIndex = selectedIndex >= 0 ? selectedIndex : firstEnabledIndex;

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target instanceof Node ? e.target : null;
      if (containerRef.current && target && !containerRef.current.contains(target)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);

  useLayoutEffect(() => {
    if (!isOpen) {
      return;
    }

    const updateDropdownPlacement = () => {
      if (!containerRef.current || !dropdownRef.current) {
        return;
      }

      const viewportGap = 12;
      const triggerGap = 6;
      const containerRect = containerRef.current.getBoundingClientRect();
      const dropdownHeight = Math.min(dropdownRef.current.scrollHeight, 280);
      const spaceBelow = window.innerHeight - containerRect.bottom - viewportGap;
      const spaceAbove = containerRect.top - viewportGap;
      const shouldOpenUp = spaceBelow < dropdownHeight && spaceAbove > spaceBelow;
      const availableSpace = Math.max(
        120,
        Math.floor((shouldOpenUp ? spaceAbove : spaceBelow) - triggerGap)
      );

      setDropDirection(shouldOpenUp ? 'up' : 'down');
      setDropdownMaxHeight(Math.min(280, availableSpace));
    };

    updateDropdownPlacement();
    window.addEventListener('resize', updateDropdownPlacement);
    window.addEventListener('scroll', updateDropdownPlacement, true);

    return () => {
      window.removeEventListener('resize', updateDropdownPlacement);
      window.removeEventListener('scroll', updateDropdownPlacement, true);
    };
  }, [isOpen, options.length]);

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        setIsOpen(false);
        window.requestAnimationFrame(() => triggerRef.current?.focus());
      }
    };

    document.addEventListener('keydown', handleKeyDown, true);
    return () => document.removeEventListener('keydown', handleKeyDown, true);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;

    const frame = window.requestAnimationFrame(() => {
      const targetIndex = activeIndex >= 0 ? activeIndex : firstEnabledIndex;
      optionRefs.current[targetIndex]?.focus();
    });

    return () => window.cancelAnimationFrame(frame);
  }, [activeIndex, firstEnabledIndex, isOpen]);

  const findNextEnabledIndex = (startIndex: number, direction: 1 | -1) => {
    if (options.length === 0) return -1;

    for (let offset = 1; offset <= options.length; offset += 1) {
      const index = (startIndex + direction * offset + options.length) % options.length;
      if (!options[index].disabled) {
        return index;
      }
    }

    return -1;
  };

  const handleSelect = (optionValue: string) => {
    onChange(optionValue);
    setIsOpen(false);
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const handleToggle = () => {
    if (!disabled) {
      if (isOpen) {
        setIsOpen(false);
        return;
      }
      setDropDirection('down');
      setDropdownMaxHeight(null);
      setIsOpen(true);
    }
  };

  const handleTriggerKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;

    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      handleToggle();
      return;
    }

    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!isOpen) {
        setDropDirection('down');
        setDropdownMaxHeight(null);
        setIsOpen(true);
      }
    }
  };

  const handleOptionKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      setIsOpen(false);
      triggerRef.current?.focus();
      return;
    }

    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      const option = options[index];
      if (option && !option.disabled) {
        handleSelect(option.value);
      }
      return;
    }

    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const nextIndex = findNextEnabledIndex(index, event.key === 'ArrowDown' ? 1 : -1);
      if (nextIndex >= 0) {
        optionRefs.current[nextIndex]?.focus();
      }
      return;
    }

    if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      const enabledIndexes = options
        .map((option, optionIndex) => (option.disabled ? -1 : optionIndex))
        .filter((optionIndex) => optionIndex >= 0);
      const targetIndex = event.key === 'Home'
        ? enabledIndexes[0]
        : enabledIndexes[enabledIndexes.length - 1];
      if (targetIndex !== undefined) {
        optionRefs.current[targetIndex]?.focus();
      }
    }
  };

  return (
    <div
      ref={containerRef}
      className={cn(
        'custom-select-wrapper flex w-full flex-col gap-1.5',
        isOpen && 'is-open',
        isOpen && dropDirection === 'up' && 'is-drop-up',
        className
      )}
    >
      {label && (
        <span id={labelId} className="custom-select-label text-[0.75rem] font-semibold uppercase tracking-[0.08em] text-muted">
          {label}
        </span>
      )}

      <button
        type="button"
        ref={triggerRef}
        className={cn(
          'custom-select-container relative flex h-11 w-full cursor-pointer items-center rounded-md border border-border bg-interactive px-3 text-sm text-foreground transition duration-200 ease-out select-none',
          isOpen && 'open border-accent-brand bg-surface',
          isOpen && dropDirection === 'down' && 'rounded-b-none border-b-transparent',
          isOpen && dropDirection === 'up' && 'rounded-t-none border-t-transparent',
          disabled && 'disabled cursor-not-allowed opacity-50',
          !disabled && 'hover:border-border-heavy hover:bg-surface-alt'
        )}
        onClick={handleToggle}
        onKeyDown={handleTriggerKeyDown}
        disabled={disabled}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-controls={isOpen ? listboxId : undefined}
        aria-labelledby={label ? `${labelId} ${valueId}` : undefined}
        aria-label={!label ? displayText : undefined}
      >
        <div className="custom-select-value flex w-full items-center justify-between gap-1.5">
          <span
            id={valueId}
            className={cn(
              'min-w-0 flex-1 truncate text-sm',
              selectedOption ? 'selected-text text-foreground' : 'placeholder-text text-subtle'
            )}
          >
            {displayText}
          </span>
          <svg
            className={cn(
              'custom-select-arrow size-4 shrink-0 text-muted transition-transform duration-200 ease-out',
              isOpen && 'rotate-180'
            )}
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <polyline points="6 10 8 12 10 10" />
            <polyline points="6 6 8 4 10 6" />
          </svg>
        </div>
      </button>

      {isOpen && (
        <div
          className={cn(
            'custom-select-dropdown absolute inset-x-0 z-[var(--z-popups)] overflow-hidden border border-border-strong bg-surface',
            dropDirection === 'up'
              ? 'custom-select-dropdown-up rounded-b-none rounded-t-md border-b-0'
              : 'custom-select-dropdown-down rounded-b-md rounded-t-none border-t-0'
          )}
          ref={dropdownRef}
          role="listbox"
          id={listboxId}
          aria-labelledby={label ? labelId : undefined}
          style={dropdownMaxHeight ? ({ '--custom-select-dropdown-max-height': `${dropdownMaxHeight}px` } as CSSProperties) : undefined}
        >
          <div className="custom-select-list ui-scrollbar-thin overflow-x-hidden overflow-y-auto py-1">
            {options.map((option, index) => (
              <button
                type="button"
                key={option.value}
                id={`${selectId}-option-${index}`}
                ref={(node) => {
                  optionRefs.current[index] = node;
                }}
                className={cn(
                  'custom-select-option flex min-h-11 w-full items-center gap-2 border-0 bg-transparent px-3 py-2 text-left text-sm text-foreground transition duration-150 ease-out select-none',
                  option.value === value && 'selected bg-interactive font-medium text-accent-brand',
                  option.disabled
                    ? 'disabled cursor-not-allowed text-subtle opacity-50'
                    : 'cursor-pointer hover:bg-surface-alt'
                )}
                disabled={option.disabled}
                onClick={() => !option.disabled && handleSelect(option.value)}
                onKeyDown={(event) => handleOptionKeyDown(event, index)}
                role="option"
                aria-selected={option.value === value}
                aria-disabled={option.disabled || undefined}
              >
                <span
                  className={cn(
                    'option-dot size-1.5 shrink-0 rounded-full bg-transparent transition-all duration-150 ease-out',
                    option.value === value && 'size-2 bg-accent-brand'
                  )}
                ></span>
                <span className="option-label min-w-0 flex-1 truncate">{option.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default CustomSelect;
