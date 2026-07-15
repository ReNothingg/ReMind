import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useFileHandler } from '../../hooks/useFileHandler';
import FilePreviewCard from '../UI/FilePreviewCard';
import FileModal from '../Modals/FileModal';
import { Utils } from '../../utils/utils';
import { useAuth } from '../../context/AuthContext';
import { useSettings } from '../../context/SettingsContext';
import { cn } from '../../utils/cn';
import { imageFilesFromClipboard } from '../../utils/clipboardFiles';
import {
    deleteRemoteDraft,
    getDeviceId,
    getRemoteDraft,
    saveRemoteDraft,
} from '../../services/reliability';

const InputArea = ({
    onSendMessage,
    onStop,
    isLoading,
    initialPrompt,
    onInitialPromptConsumed = undefined,
    onOpenAuth,
    isReadOnly = false,
    variant = 'default',
    showDynamicWarning = false,
    currentSessionId = null,
}) => {
    const [text, setText] = useState(initialPrompt || '');
    const [quotes, setQuotes] = useState([]);
    const [fileModal, setFileModal] = useState({ isOpen: false, file: null, content: null });
    const [expanded, setExpanded] = useState(false);
    const [webSearchEnabled, setWebSearchEnabled] = useState(false);

    const textareaRef = useRef(null);
    const quoteButtonRef = useRef(null);
    const draftRevisionRef = useRef<number | null>(null);
    const draftLoadedRef = useRef(false);

    const { isAuthenticated } = useAuth();
    const { settings } = useSettings();
    const { t } = useTranslation();

    const fileUploadsEnabled = isAuthenticated && !isReadOnly;
    const automaticWebSearch = !!settings.automaticWebSearch;

    const manualWebSearchEnabled = !automaticWebSearch && webSearchEnabled;
    const draftStorageKey = `remind_chat_draft_v2:${currentSessionId || 'new'}`;

    useEffect(() => {
        let cancelled = false;
        draftLoadedRef.current = false;
        draftRevisionRef.current = null;
        const localRaw = localStorage.getItem(draftStorageKey);
        const local = localRaw ? (() => {
            try { return JSON.parse(localRaw); } catch { return null; }
        })() : null;
        if (!initialPrompt && settings.autoSave && typeof local?.content === 'string') {
            queueMicrotask(() => {
                if (!cancelled) setText(local.content);
            });
        }
        if (!isAuthenticated || !settings.autoSave || !navigator.onLine) {
            draftLoadedRef.current = true;
            return () => { cancelled = true; };
        }
        void getRemoteDraft().then((remote) => {
            if (cancelled) return;
            draftRevisionRef.current = remote?.revision ?? 0;
            if (
                !initialPrompt && remote?.session_id === currentSessionId &&
                typeof remote.content === 'string' &&
                Number(remote.updated_at || 0) > Number(local?.updatedAt || 0)
            ) {
                setText(remote.content);
            }
        }).catch(() => undefined).finally(() => {
            if (!cancelled) draftLoadedRef.current = true;
        });
        return () => { cancelled = true; };
    }, [currentSessionId, draftStorageKey, initialPrompt, isAuthenticated, settings.autoSave]);

    useEffect(() => {
        if (!settings.autoSave || !draftLoadedRef.current) return;
        let cancelled = false;
        const updatedAt = Date.now();
        localStorage.setItem(draftStorageKey, JSON.stringify({ content: text, updatedAt }));
        if (!isAuthenticated || !navigator.onLine) return;
        const timer = window.setTimeout(() => {
            void saveRemoteDraft(text, currentSessionId, draftRevisionRef.current)
                .then(async (draft) => {
                    if (cancelled) return;
                    if (draft.device_id !== getDeviceId() && draft.content !== text) {
                        const resolved = await saveRemoteDraft(
                            text,
                            currentSessionId,
                            draft.revision
                        );
                        if (cancelled) return;
                        draftRevisionRef.current = resolved.revision;
                    } else {
                        draftRevisionRef.current = draft.revision;
                    }
                })
                .catch(() => undefined);
        }, 700);
        return () => {
            cancelled = true;
            window.clearTimeout(timer);
        };
    }, [currentSessionId, draftStorageKey, isAuthenticated, settings.autoSave, text]);

    useEffect(() => {
        if (!initialPrompt) {
            return;
        }

        const frame = window.requestAnimationFrame(() => {
            setText((currentText) => (currentText === initialPrompt ? currentText : initialPrompt));
            textareaRef.current?.focus();
        });

        return () => window.cancelAnimationFrame(frame);
    }, [initialPrompt]);

    const dynamicWarning = useMemo(() => {
        if (!showDynamicWarning) return;
        const phrases = t('warnings.dynamicPhrases', { returnObjects: true });
        const list = Array.isArray(phrases) ? phrases : [phrases].filter(Boolean);
        const fallback = list[0] || '';
        return Utils.getRandomPhrase(list.length > 0 ? list : [fallback], fallback);
    }, [showDynamicWarning, t]);

    const {
        files,
        isDragActive,
        fileInputRef,
        addFiles,
        removeFile,
        clearFiles,
        handleFileInputChange,
        handleDragEnter,
        handleDragLeave,
        handleDragOver,
        handleDrop,
    } = useFileHandler({ enabled: fileUploadsEnabled });

    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            const nextHeight = text.trim()
                ? Math.min(textareaRef.current.scrollHeight, 200)
                : 44;
            textareaRef.current.style.height = `${nextHeight}px`;
        }
    }, [text, quotes]);

    useEffect(() => {
        const el = textareaRef.current;
        if (!el) return;

        const frame = window.requestAnimationFrame(() => {
            const threshold = 110;
            const scrollHeight = el.scrollHeight;
            const nextExpanded = scrollHeight > threshold || el.clientHeight > threshold;
            setExpanded((current) => (current === nextExpanded ? current : nextExpanded));
        });

        return () => window.cancelAnimationFrame(frame);
    }, [text, quotes]);

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
            return;
        }

        const effectiveFiles = fileUploadsEnabled ? files : [];
        const hasMessageContent = text.trim() || effectiveFiles.length > 0 || quotes.length > 0;
        if (!hasMessageContent) return;

        let fullText = text;
        if (quotes.length > 0) {
            const quotedText = quotes.map((quote) => `> ${quote}`).join('\n');
            fullText = quotedText + (text ? `\n\n${text}` : '');
        }

        onSendMessage(fullText, effectiveFiles, {
            webSearch: manualWebSearchEnabled,
            autoWebSearch: automaticWebSearch,
            censorship: false,
        });
        onInitialPromptConsumed?.();

        setText('');
        localStorage.removeItem(draftStorageKey);
        if (isAuthenticated && navigator.onLine) void deleteRemoteDraft().catch(() => undefined);
        setQuotes([]);
        clearFiles();
    };

    const handleKeyDown = (event) => {
        if (event.key !== 'Enter') {
            return;
        }

        const requireCtrlEnter = !!settings.requireCtrlEnterToSend;

        if (requireCtrlEnter) {
            if (event.ctrlKey || event.metaKey) {
                event.preventDefault();
                if (!isLoading && !isReadOnly) {
                    handleSend();
                }
            }
            return;
        }

        if (event.ctrlKey || event.metaKey || !event.shiftKey) {
            event.preventDefault();
            if (!isLoading && !isReadOnly) {
                handleSend();
            }
        }
    };

    const handlePaste = useCallback((event) => {
        if (!fileUploadsEnabled || isReadOnly) {
            return;
        }
        const pastedImages = imageFilesFromClipboard(
            event.clipboardData?.items,
            Date.now(),
            t('files.pastedImageName'),
        );
        if (pastedImages.length === 0) {
            return;
        }
        event.preventDefault();
        addFiles(pastedImages);
    }, [addFiles, fileUploadsEnabled, isReadOnly, t]);

    const removeQuote = (index) => {
        setQuotes((prev) => prev.filter((_, currentIndex) => currentIndex !== index));
    };

    const hideQuoteButton = useCallback(() => {
        if (quoteButtonRef.current) {
            quoteButtonRef.current.style.display = 'none';
            quoteButtonRef.current.classList.remove('visible');
        }
    }, []);

    const addQuote = useCallback(
        (quoteText) => {
            if (quoteText && !quotes.includes(quoteText)) {
                setQuotes((prev) => [...prev, quoteText]);
            }
        },
        [quotes]
    );

    const showQuoteButton = useCallback(
        (range, selectedText) => {
            if (!quoteButtonRef.current) {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'quote-action-button ui-selection-quote-button';
                button.textContent = t('composer.quote');
                button.onclick = (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    addQuote(selectedText);
                    window.getSelection()?.removeAllRanges();
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
            button.classList.add('visible');
        },
        [addQuote, hideQuoteButton, t]
    );

    const handleMouseUp = useCallback(
        (event) => {
            const eventTarget = event.target;
            if (eventTarget instanceof Element && eventTarget.closest('button, .quote-button')) return;

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
                const targetElement =
                    commonAncestor.nodeType === Node.ELEMENT_NODE
                        ? commonAncestor as Element
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
        },
        [showQuoteButton, hideQuoteButton]
    );

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

    const effectiveFileCount = fileUploadsEnabled ? files.length : 0;
    const hasContent = Boolean(text.trim() || effectiveFileCount > 0 || quotes.length > 0);
    const hasQuotes = quotes.length > 0;
    const sendButtonClass = isLoading
        ? 'stop-button'
        : hasContent
          ? 'send-mode-button'
          : 'audio-link-button';

    const sendButtonTitle = isLoading
        ? t('composer.stop')
        : hasContent
          ? settings.requireCtrlEnterToSend
              ? t('composer.sendCtrlEnter')
              : t('composer.sendEnter')
          : t('composer.joinDialog');

    return (
        <>
            <div
                className={cn(
                    'drag-overlay ui-drag-overlay',
                    isDragActive ? 'active visible opacity-100' : 'invisible opacity-0 pointer-events-none'
                )}
                id="dragOverlay"
                role="status"
                aria-live="polite"
                aria-hidden={!isDragActive}
            >
                <div
                    className={cn(
                        'drop-zone ui-dropzone-card',
                        isDragActive && 'drag-over ui-dropzone-card-active'
                    )}
                >
                    <div className="drop-zone-icon ui-dropzone-icon">
                        <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                            <polyline points="17 8 12 3 7 8" />
                            <line x1="12" x2="12" y1="3" y2="15" />
                        </svg>
                    </div>
                    
                    <div className="drop-zone-text mb-2 text-lg font-medium text-foreground">{t('composer.dragDropTitle')}</div>
                    <div className="drop-zone-subtext text-sm text-muted">{t('composer.dragDropSubtitle')}</div>
                </div>
            </div>

            <footer
                className={cn(
                    'main-input-area ui-main-input-shell',
                    variant === 'landing' && 'landing',
                    expanded && 'expanded',
                    isDragActive && 'drag-over'
                )}
            >
                <input
                    type="file"
                    id="fileInput"
                    multiple
                    accept="*/*"
                    style={{ display: 'none' }}
                    ref={fileInputRef}
                    onChange={(event) => {
                        handleFileInputChange(event);
                        if (event.target) event.target.value = '';
                    }}
                />

                {files.length > 0 && (
                    <div className="attach-area ui-composer-attachments">
                        <div id="previewContainer" className="preview-container ui-composer-preview-list">
                            {files.map((file, index) => (
                                <FilePreviewCard
                                    key={index}
                                    file={file}
                                    onRemove={() => removeFile(index)}
                                    onPreview={(selectedFile, content) => setFileModal({ isOpen: true, file: selectedFile, content })}
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

                <div className={cn('input-wrapper ui-composer-shell', hasQuotes && 'has-quotes')}>
                    {hasQuotes && (
                        <div
                            id="quotePreviewArea"
                            className="quote-preview-area ui-composer-quote-stack ui-scrollbar-thin"
                            role="group"
                            aria-label={t('composer.quote')}
                        >
                            {quotes.map((quote, index) => (
                            <div key={index} className="quote-item ui-composer-quote-card">
                                <blockquote className="overflow-hidden whitespace-pre-wrap break-words text-[var(--color-text-secondary)] italic leading-6">
                                    {quote}
                                </blockquote>
                                <button
                                    type="button"
                                    className="quote-item-dismiss ui-composer-quote-dismiss"
                                    title={t('composer.removeQuote')}
                                    aria-label={t('composer.removeQuote')}
                                    onClick={() => removeQuote(index)}
                                >
                                    x
                                </button>
                            </div>
                            ))}
                        </div>
                    )}

                    {showDynamicWarning && dynamicWarning && (
                        <div
                            id="dynamicWarningLabel"
                            className="warning-label ui-hint-pill absolute bottom-[calc(100%+var(--main-input-area-padding)+var(--spacing-unit))] left-1/2 max-w-[calc(100%-32px)] -translate-x-1/2"
                            role="status"
                            aria-live="polite"
                        >
                            {dynamicWarning}
                        </div>
                    )}

                    <div className="ui-composer-input-row">
                        {isAuthenticated && !isReadOnly ? (
                            <button
                                type="button"
                                className="attach-button ui-composer-icon-button ml-[calc(var(--spacing-unit)*0.75)]"
                                title={t('composer.attachFiles')}
                                aria-label={t('composer.attachFiles')}
                                onClick={() => fileInputRef.current?.click()}
                            />
                        ) : (
                            <button
                                type="button"
                                className="attach-button ui-composer-icon-button ml-[calc(var(--spacing-unit)*0.75)] cursor-not-allowed opacity-50"
                                title={isReadOnly ? t('composer.attachUnavailableReadOnly') : t('composer.attachRequiresAccount')}
                                aria-label={t('composer.attachUnavailable')}
                                onClick={(event) => {
                                    event.preventDefault();
                                    if (!isReadOnly && onOpenAuth) onOpenAuth();
                                }}
                            />
                        )}

                        {!automaticWebSearch && (
                            <button
                                type="button"
                                className={cn('web-search-toggle', manualWebSearchEnabled && 'active')}
                                title={manualWebSearchEnabled ? t('composer.webSearchOn') : t('composer.webSearchOff')}
                                aria-label={manualWebSearchEnabled ? t('composer.webSearchOn') : t('composer.webSearchOff')}
                                aria-pressed={manualWebSearchEnabled}
                                disabled={isReadOnly}
                                onClick={() => {
                                    if (!isReadOnly) {
                                        setWebSearchEnabled((enabled) => !enabled);
                                    }
                                }}
                            >
                                <img src="/icons/ui/web.svg" alt="" aria-hidden="true" />
                                <span>{t('composer.webSearchLabel')}</span>
                            </button>
                        )}

                        <textarea
                            id="promptInput"
                            ref={textareaRef}
                            className="ui-composer-textarea"
                            placeholder={isReadOnly ? t('composer.placeholderReadOnly') : t('composer.placeholder')}
                            aria-label={t('composer.ariaInput')}
                            aria-describedby={showDynamicWarning && dynamicWarning ? 'dynamicWarningLabel' : undefined}
                            rows={1}
                            value={text}
                            onChange={(event) => setText(event.target.value)}
                            onKeyDown={handleKeyDown}
                            onPaste={handlePaste}
                            disabled={isReadOnly}
                        ></textarea>

                        <button
                            id="sendButton"
                            type="button"
                            className={cn(
                                'send-button ui-composer-icon-button ml-[calc(var(--spacing-unit)*0.75)]',
                                hasContent || isLoading
                                    ? 'bg-foreground text-white hover:brightness-110'
                                    : 'bg-surface-alt',
                                sendButtonClass
                            )}
                            title={isReadOnly ? t('chat.readOnly') : sendButtonTitle}
                            aria-label={isLoading ? t('composer.stop') : sendButtonTitle}
                            onClick={handleSend}
                            disabled={isReadOnly}
                        >
                        </button>
                    </div>
                </div>
            </footer>
        </>
    );
};

export default InputArea;
