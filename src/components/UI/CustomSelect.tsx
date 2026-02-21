import React, { useState, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import '../../styles/components/ui/custom-select.css';

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
      className={`custom-select-wrapper ${className}`}
    >
      {label && <label className="custom-select-label">{label}</label>}

      <div
        className={`custom-select-container ${isOpen ? 'open' : ''} ${disabled ? 'disabled' : ''}`}
        onClick={handleToggle}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-expanded={isOpen}
        aria-label={label}
      >
        <div className="custom-select-value">
          <span className={selectedOption ? 'selected-text' : 'placeholder-text'}>
            {displayText}
          </span>
          <svg
            className="custom-select-arrow"
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
          <div className="custom-select-dropdown" ref={dropdownRef}>
            <div className="custom-select-list">
              {options.map((option) => (
                <div
                  key={option.value}
                  className={`custom-select-option ${
                    option.value === value ? 'selected' : ''
                  } ${option.disabled ? 'disabled' : ''}`}
                  onClick={() => !option.disabled && handleSelect(option.value)}
                  role="option"
                  aria-selected={option.value === value}
                >
                  <span className="option-dot"></span>
                  <span className="option-label">{option.label}</span>
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
