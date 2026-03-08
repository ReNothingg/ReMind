import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '../../utils/cn';

const CustomSelect = ({
  value,
  onChange,
  options,
  label,
  disabled = false,
  className = '',
  placeholder
}) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef(null);
  const dropdownRef = useRef(null);
  const selectedOptionRef = useRef(null);
  const selectedOption = options.find(opt => opt.value === value);
  const displayText = selectedOption?.label || placeholder || t('common.selectOption');
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setIsOpen(false);
        return;
      }

      const currentIndex = options.findIndex(opt => opt.value === value);
      let nextIndex = currentIndex;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        nextIndex = currentIndex + 1 < options.length ? currentIndex + 1 : 0;
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        nextIndex = currentIndex - 1 >= 0 ? currentIndex - 1 : options.length - 1;
      } else if (e.key === 'Enter') {
        e.preventDefault();
        setIsOpen(false);
        return;
      }

      if (nextIndex !== currentIndex) {
        onChange(options[nextIndex].value);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, value, options, onChange]);

  const handleSelect = (optionValue) => {
    onChange(optionValue);
    setIsOpen(false);
  };

  const handleToggle = () => {
    if (!disabled) {
      setIsOpen(!isOpen);
    }
  };

  return (
    <div
      ref={containerRef}
      className={cn('custom-select-wrapper flex w-full flex-col gap-1.5', className)}
    >
      {label && (
        <label className="custom-select-label text-[0.75rem] font-semibold uppercase tracking-[0.08em] text-muted">
          {label}
        </label>
      )}

      <div
        className={cn(
          'custom-select-container relative flex h-8 w-full cursor-pointer items-center rounded-md border border-border bg-interactive px-2 text-sm text-foreground transition duration-200 ease-out select-none',
          isOpen && 'open rounded-b-none border-accent-brand bg-surface',
          disabled && 'disabled cursor-not-allowed opacity-50',
          !disabled && 'hover:border-border-heavy hover:bg-surface-alt'
        )}
        onClick={handleToggle}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-expanded={isOpen}
        aria-label={label}
      >
        <div className="custom-select-value flex w-full items-center justify-between gap-1.5">
          <span
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
          >
            <polyline points="6 10 8 12 10 10" />
            <polyline points="6 6 8 4 10 6" />
          </svg>
        </div>

        {isOpen && (
          <div
            className="custom-select-dropdown absolute inset-x-0 top-[calc(100%-1px)] z-[1000] overflow-hidden rounded-b-md border border-border-strong border-t-0 bg-surface shadow-[var(--shadow-lg)]"
            ref={dropdownRef}
          >
            <div className="custom-select-list ui-scrollbar-thin max-h-70 overflow-x-hidden overflow-y-auto py-1">
              {options.map((option) => (
                <div
                  key={option.value}
                  className={cn(
                    'custom-select-option flex items-center gap-2 px-2.5 py-2 text-sm text-foreground transition duration-150 ease-out select-none',
                    option.value === value && 'selected bg-interactive font-medium text-accent-brand',
                    option.disabled
                      ? 'disabled cursor-not-allowed text-subtle opacity-50'
                      : 'cursor-pointer hover:bg-surface-alt'
                  )}
                  onClick={() => !option.disabled && handleSelect(option.value)}
                  role="option"
                  aria-selected={option.value === value}
                >
                  <span
                    className={cn(
                      'option-dot size-1.5 shrink-0 rounded-full bg-transparent transition-all duration-150 ease-out',
                      option.value === value && 'size-2 bg-accent-brand'
                    )}
                  ></span>
                  <span className="option-label min-w-0 flex-1 truncate">{option.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default CustomSelect;
