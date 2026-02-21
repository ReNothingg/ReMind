import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useFileHandler } from '../../hooks/useFileHandler';
import FilePreviewCard from '../UI/FilePreviewCard';
import FileModal from '../Modals/FileModal';
import { Utils } from '../../utils/utils';
import { useAuth } from '../../context/AuthContext';
import { useSettings } from '../../context/SettingsContext';

const InputArea = ({ onSendMessage, onStop, isLoading, initialPrompt, onOpenAuth, isReadOnly = false, variant = 'default', showDynamicWarning = true }) => {
    const [text, setText] = useState(initialPrompt || '');
    const [quotes, setQuotes] = useState([]);
    const [fileModal, setFileModal] = useState({ isOpen: false, file: null, content: null });
    const [dynamicWarning, setDynamicWarning] = useState('');
    const textareaRef = useRef(null);
    const quoteButtonRef = useRef(null);
    const { isAuthenticated } = useAuth();
    const { settings } = useSettings();
    const { t, i18n } = useTranslation();
    useEffect(() => {
        if (initialPrompt && initialPrompt !== text) {
            setTimeout(() => {
                setText(initialPrompt);
                if (textareaRef.current) {
                    textareaRef.current.focus();
                }
            }, 0);
        }
    }, [initialPrompt]); // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(() => {
        if (!showDynamicWarning) return;
        const phrases = t('warnings.dynamicPhrases', { returnObjects: true });
        const list = Array.isArray(phrases) ? phrases : [phrases].filter(Boolean);
        const fallback = list[0] || '';
        const warningText = Utils.getRandomPhrase(list.length > 0 ? list : [fallback], fallback);
        setDynamicWarning(warningText);
    }, [showDynamicWarning, i18n.resolvedLanguage]); // eslint-disable-line react-hooks/exhaustive-deps
    const {
        files,
        isDragActive,
        fileInputRef,
        removeFile,
        clearFiles,
        handleFileInputChange,
        handleDragEnter,
        handleDragLeave,
        handleDragOver,
        handleDrop,
        VALID_IMAGE_MIME_TYPES
    } = useFileHandler();
    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px';
        }
    }, [text, quotes]);
    const [expanded, setExpanded] = useState(false);
    useEffect(() => {
        const el = textareaRef.current;
        if (!el) return;
        const threshold = 110; // высота в px, после которой переключаемся в "expanded"
        const scrollH = el.scrollHeight;
        setExpanded(scrollH > threshold || el.clientHeight > threshold);
    }, [text]);
    useEffect(() => {
        document.addEventListener('dragenter', handleDragEnter);
        document.addEventListener('dragleave', handleDragLeave);
        document.addEventListener('dragover', handleDragOver);
        document.addEventListener('drop', handleDrop);
        return () => {
            document.removeEventListener('dragenter', handleDragEnter);
            document.removeEventListener('dragleave', handleDragLeave);
            document.removeEventListener('dragover', handleDragOver);
            document.removeEventListener('drop', handleDrop);
        };
    }, [handleDragEnter, handleDragLeave, handleDragOver, handleDrop]);

    const handleSend = () => {
        if (isReadOnly) {
            return;
        }
        if (isLoading) {
            onStop();
        } else {
            const hasContent = text.trim() || files.length > 0 || quotes.length > 0;
            if (!hasContent) return;
            let fullText = text;
            if (quotes.length > 0) {
                const quotedText = quotes.map(q => `> ${q}`).join('\n');
                fullText = quotedText + (text ? '\n\n' + text : '');
            }

            onSendMessage(fullText, files, {
                webSearch: false, // webSearchEnabled,
                censorship: false // censorshipEnabled
            });
            setText('');
            setQuotes([]);
            clearFiles();
        }
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter') {
            const requireCtrlEnter = !!settings.requireCtrlEnterToSend;

            if (requireCtrlEnter) {
                if (e.ctrlKey || e.metaKey) {
                    e.preventDefault();
                    if (!isLoading && !isReadOnly) {
                        handleSend();
                    }
                }
                return;
            }

            if (e.ctrlKey || e.metaKey || !e.shiftKey) {
                e.preventDefault();
                if (!isLoading && !isReadOnly) {
                    handleSend();
                }
            }
        }
    };

    const removeQuote = (index) => {
        setQuotes(prev => prev.filter((_, i) => i !== index));
    };
    const hideQuoteButton = useCallback(() => {
        if (quoteButtonRef.current) {
            quoteButtonRef.current.style.display = 'none';
        }
    }, []);

    const addQuote = useCallback((quoteText) => {
        if (quoteText && !quotes.includes(quoteText)) {
            setQuotes(prev => [...prev, quoteText]);
        }
    }, [quotes]);

    const showQuoteButton = useCallback((range, selectedText) => {
        if (!quoteButtonRef.current) {
            const button = document.createElement('button');
            button.className = 'quote-action-button';
            button.innerHTML = `📎 ${t('composer.quote')}`;
            button.onclick = (e) => {
                e.preventDefault();
                e.stopPropagation();
                addQuote(selectedText);
                window.getSelection().removeAllRanges();
                hideQuoteButton();
            };
            document.body.appendChild(button);
            quoteButtonRef.current = button;
        }

        const rect = range.getBoundingClientRect();
        const button = quoteButtonRef.current;
        button.style.position = 'fixed';
        button.style.left = `${rect.left + rect.width / 2 - 60}px`;
        button.style.top = `${rect.top - 40}px`;
        button.style.display = 'block';
        button.style.zIndex = '10000';
    }, [addQuote, hideQuoteButton]);
    const handleMouseUp = useCallback((e) => {
        if (e.target.closest('button, .quote-button')) return;

        setTimeout(() => {
            const selection = window.getSelection();
            if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
                hideQuoteButton();
                return;
            }

            const selectedText = selection.toString().trim();
            if (!selectedText) {
                hideQuoteButton();
                return;
            }

            const range = selection.getRangeAt(0);
            const commonAncestor = range.commonAncestorContainer;
            const targetElement = commonAncestor.nodeType === Node.ELEMENT_NODE
                ? commonAncestor
                : commonAncestor.parentElement;

            if (!targetElement) {
                hideQuoteButton();
                return;
            }
            const messageTextElement = targetElement.closest('.ai-message .message-text');
            const isInsideDisallowed = targetElement.closest(
                'pre, code, a, button, .actions-bar, .translation-panel, .audio-player-container, ' +
                '.thinking-process-block, .variants-nav, .canvas-host-for-message, .quote-action-button, ' +
                '.quote-preview-area, #promptInput, .error-display-panel, .game-host-div'
            );

            if (messageTextElement && !isInsideDisallowed) {
                showQuoteButton(range, selectedText);
            } else {
                hideQuoteButton();
            }
        }, 10);
    }, [showQuoteButton, hideQuoteButton]);

    useEffect(() => {
        document.addEventListener('mouseup', handleMouseUp);
        const handleSelectionChange = () => {
            const selection = window.getSelection();
            if (!selection || selection.isCollapsed) {
                hideQuoteButton();
            }
        };
        document.addEventListener('selectionchange', handleSelectionChange);
        return () => {
            document.removeEventListener('mouseup', handleMouseUp);
            document.removeEventListener('selectionchange', handleSelectionChange);
            if (quoteButtonRef.current) {
                quoteButtonRef.current.remove();
            }
        };
    }, [handleMouseUp, hideQuoteButton]);
    const sendButtonClass = isLoading
        ? 'stop-button'
        : (text.trim() || files.length > 0 || quotes.length > 0)
            ? 'send-mode-button'
            : 'audio-link-button';

    const hasContent = Boolean(text.trim() || files.length > 0 || quotes.length > 0);

    const sendButtonTitle = isLoading
        ? t('composer.stop')
        : hasContent
            ? (settings.requireCtrlEnterToSend ? t('composer.sendCtrlEnter') : t('composer.sendEnter'))
            : t('composer.joinDialog');

    return (
        <>
            <div className={`drag-overlay ${isDragActive ? 'active' : ''}`} id="dragOverlay">
                <div className={`drop-zone ${isDragActive ? 'drag-over' : ''}`}>
                    <div className="drop-zone-icon">
                        <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                            <polyline points="17 8 12 3 7 8"/>
                            <line x1="12" x2="12" y1="3" y2="15"/>
                        </svg>
                    </div>
                    <div className="drop-zone-text">{t('composer.dragDropTitle')}</div>
                    <div className="drop-zone-subtext">{t('composer.dragDropSubtitle')}</div>
                </div>
            </div>

            <footer className={`main-input-area ${variant === 'landing' ? 'landing' : ''} ${expanded ? 'expanded' : ''} ${isDragActive ? 'drag-over' : ''}`}>
                <input
                    type="file"
                    id="fileInput"
                    multiple
                    accept="*/*"
                    style={{ display: 'none' }}
                    ref={fileInputRef}
                    onChange={(e) => {
                        handleFileInputChange(e);
                        if (e.target) e.target.value = '';
                    }}
                />

                {files.length > 0 && (
                    <div className="attach-area" style={{ maxHeight: '140px', opacity: 1, padding: '6px' }}>
                        <div id="previewContainer" className="preview-container">
                            {files.map((file, index) => (
                                <FilePreviewCard
                                    key={index}
                                    file={file}
                                    onRemove={() => removeFile(index)}
                                    onPreview={(file, content) => setFileModal({ isOpen: true, file, content })}
                                />
                            ))}
                        </div>
                    </div>
                )}

            <FileModal
                isOpen={fileModal.isOpen}
                onClose={() => setFileModal({ isOpen: false, file: null, content: null })}
                file={fileModal.file}
                content={fileModal.content}
            />

            <div className="input-wrapper">
                {isAuthenticated && !isReadOnly ? (
                    <label htmlFor="fileInput" className="attach-button" title={t('composer.attachFiles')} aria-label={t('composer.attachFiles')}></label>
                ) : (
                    <label
                        className="attach-button"
                        title={isReadOnly ? t('composer.attachUnavailableReadOnly') : t('composer.attachRequiresAccount')}
                        aria-label={t('composer.attachUnavailable')}
                        onClick={(e) => {
                            e.preventDefault();
                            if (!isReadOnly && onOpenAuth) onOpenAuth();
                        }}
                        style={{ opacity: 0.5, cursor: 'not-allowed' }}
                    ></label>
                )}

                <div id="quotePreviewArea" className="quote-preview-area">
                    {quotes.map((quote, index) => (
                        <div key={index} className="quote-item">
                            <blockquote>{quote}</blockquote>
                            <button
                                className="quote-item-dismiss"
                                title={t('composer.removeQuote')}
                                onClick={() => removeQuote(index)}
                            >
                                ×
                            </button>
                        </div>
                    ))}
                </div>

                {showDynamicWarning && dynamicWarning && (
                    <div id="dynamicWarningLabel" className="warning-label">
                        {dynamicWarning}
                    </div>
                )}

                {}

                <textarea
                    id="promptInput"
                    ref={textareaRef}
                    placeholder={isReadOnly ? t('composer.placeholderReadOnly') : t('composer.placeholder')}
                    aria-label={t('composer.ariaInput')}
                    rows={1}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    disabled={isReadOnly}
                ></textarea>

                <button
                    id="sendButton"
                    type="button"
                    className={`send-button ${sendButtonClass}`}
                    title={isReadOnly ? t('chat.readOnly') : sendButtonTitle}
                    aria-label={isLoading ? t('composer.stop') : t('composer.send')}
                    onClick={handleSend}
                    disabled={isReadOnly}
                >
                </button>
            </div>
        </footer>
        </>
    );
};

export default InputArea;
