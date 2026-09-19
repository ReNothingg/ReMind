import { readComposerTools, toolIconPath } from '../../features/chat/composerTools';
import { ComposerTextEditor, type ComposerTextEditorHandle } from '../../features/chat/components/ComposerTextEditor';
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useFileHandler } from '../../hooks/useFileHandler';
import FilePreviewCard from '../UI/FilePreviewCard';
import FileModal from '../Modals/FileModal';
import { Utils } from '../../utils/utils';
import { useAuth } from '../../context/AuthContext';
import { useSettings } from '../../context/SettingsContext';
import { cn } from '../../utils/cn';
import { imageFilesFromClipboard } from '../../utils/clipboardFiles';
import { CHAT_UPLOAD_ACCEPT, CHAT_UPLOAD_MAX_TOTAL_BYTES } from '../../utils/constants';
import ModelSelector from '../../features/chat/components/ModelSelector';
import { isImageToolModel, type ChatModel } from '../../features/chat/modelSelection';
import type { ComposerToolOption, ThinkingLevel } from '../../services/api';
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
    currentModel = '',
    models = [] as ChatModel[],
    availableTools = [] as ComposerToolOption[],
    onModelChange = undefined,
    thinkingLevel = 'medium' as ThinkingLevel,
    onThinkingLevelChange = undefined,
}) => {
    const [text, setText] = useState(initialPrompt || '');
    const [quotes, setQuotes] = useState([]);
    const [fileModal, setFileModal] = useState({ isOpen: false, file: null, content: null });
    const [expanded, setExpanded] = useState(false);
    const [mention, setMention] = useState<{ start: number; end: number; query: string } | null>(null);
    const [activeSuggestion, setActiveSuggestion] = useState(0);
    const toolMenuId = useId();
    const composerRef = useRef<HTMLElement | null>(null);

    const textareaRef = useRef<ComposerTextEditorHandle | null>(null);
    const quoteButtonRef = useRef(null);
    const draftRevisionRef = useRef<number | null>(null);
    const draftLoadedRef = useRef(false);
    const [draftLoadRevision, setDraftLoadRevision] = useState(0);

    const { isAuthenticated } = useAuth();
    const { settings } = useSettings();
    const { t } = useTranslation();

    const fileUploadsEnabled = isAuthenticated && !isReadOnly;
    const automaticWebSearch = !!settings.automaticWebSearch;

    const tools = [
        ...availableTools.map((tool) => ({
            id: tool.id, label: t(tool.titleKey), available: tool.available,
            description: t(!tool.available && tool.unavailableKey ? tool.unavailableKey : tool.descriptionKey),
            aliases: tool.id === 'web' ? 'web search поиск сеть' : tool.id,
        })),
        ...models.filter(isImageToolModel).filter((model) => !availableTools.some((tool) => tool.id === model.id)).map((model) => ({
            id: model.id, label: t('composer.tools.image'),
            description: t(model.id === 'demo_image' ? 'composer.tools.imageDemoDescription' : 'composer.tools.imageDescription'),
            available: true, aliases: 'image изображение картинка ' + model.id,
        })),
    ];
    const editorTools = tools.filter((tool) => tool.available).map((tool) => ({ ...tool, removeLabel: t('composer.tools.remove', { tool: tool.label }) }));
    const { text: messageText, selected: selectedTools } = readComposerTools(text, editorTools);
    const toolQuery = mention?.query.toLocaleLowerCase() || '';
    const exactToolMatch = (tool: typeof tools[number]) => toolQuery !== '' && (
        tool.id === toolQuery || tool.label.toLocaleLowerCase() === toolQuery || tool.aliases.split(' ').includes(toolQuery)
    );
    const suggestions = tools
        .filter((tool) => `${tool.label} ${tool.aliases}`.toLocaleLowerCase().includes(toolQuery))
        .sort((a, b) => Number(exactToolMatch(b)) - Number(exactToolMatch(a)));
    const manualWebSearchEnabled = selectedTools.some((tool) => tool.id === 'web');

    const updateMention = (value: string, caret: number) => {
        const match = /(?:^|\s)@([^\s@{}]*)$/.exec(value.slice(0, caret));
        setMention(match ? { start: caret - match[1].length - 1, end: caret, query: match[1] } : null);
        setActiveSuggestion(0);
    };
    const selectTool = (id: string) => {
        if (!mention || isReadOnly || !tools.some((tool) => tool.id === id && tool.available)) return;
        textareaRef.current?.insertTool(mention.start, mention.end, id);
        setMention(null);
    };
    useEffect(() => {
        const menu = document.getElementById(toolMenuId);
        const option = document.getElementById(`${toolMenuId}-${activeSuggestion}`);
        if (!menu || !option) return;
        if (option.offsetTop < menu.scrollTop) menu.scrollTop = option.offsetTop;
        else if (option.offsetTop + option.offsetHeight > menu.scrollTop + menu.clientHeight) {
            menu.scrollTop = option.offsetTop + option.offsetHeight - menu.clientHeight;
        }
    }, [activeSuggestion, mention?.query, toolMenuId]);

    useEffect(() => {
        const dismiss = (event: Event) => {
            if (!composerRef.current?.contains(event.target as Node)) setMention(null);
        };
        const blur = () => setMention(null);
        document.addEventListener('pointerdown', dismiss);
        document.addEventListener('focusin', dismiss);
        window.addEventListener('blur', blur);
        return () => {
            document.removeEventListener('pointerdown', dismiss);
            document.removeEventListener('focusin', dismiss);
            window.removeEventListener('blur', blur);
        };
    }, []);
    useEffect(() => {
        const frame = requestAnimationFrame(() => {
            setMention(null);
        });
        return () => cancelAnimationFrame(frame);
    }, [currentSessionId]);
    const draftStorageKey = `remind_chat_draft_v2:${currentSessionId || 'new'}`;

    useEffect(() => {
        let cancelled = false;
        draftLoadedRef.current = false;
        draftRevisionRef.current = null;
        const localRaw = localStorage.getItem(draftStorageKey);
        const local = localRaw ? (() => {
            try { return JSON.parse(localRaw); } catch { return null; }
        })() : null;
        if (!initialPrompt) {
            queueMicrotask(() => {
                if (!cancelled) setText(typeof local?.content === 'string' ? local.content : '');
            });
        }
        const finishLoading = () => {
            if (cancelled) return;
            draftLoadedRef.current = true;
            setDraftLoadRevision((revision) => revision + 1);
        };
        if (!isAuthenticated || !navigator.onLine) {
            queueMicrotask(finishLoading);
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
        }).catch(() => undefined).finally(finishLoading);
        return () => { cancelled = true; };
    }, [currentSessionId, draftStorageKey, initialPrompt, isAuthenticated]);

    useEffect(() => {
        if (!draftLoadedRef.current) return;
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
    }, [currentSessionId, draftStorageKey, draftLoadRevision, isAuthenticated, text]);

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
        formatFileSize,
        handleFileInputChange,
        handleDragEnter,
        handleDragLeave,
        handleDragOver,
        handleDrop,
    } = useFileHandler({ enabled: fileUploadsEnabled });

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
        const hasMessageContent = messageText.trim() || effectiveFiles.length > 0 || quotes.length > 0;
        if (!hasMessageContent) return;

        let fullText = messageText;
        let composerContent = text;
        if (quotes.length > 0) {
            const quotedText = quotes.map((quote) => `> ${quote}`).join('\n');
            fullText = quotedText + (messageText ? `\n\n${messageText}` : '');
            composerContent = quotedText + (text ? `\n\n${text}` : '');
        }

        onSendMessage(fullText, effectiveFiles, {
            webSearch: manualWebSearchEnabled,
            autoWebSearch: automaticWebSearch,
            composerContent: selectedTools.length ? composerContent : undefined,
            tools: [...new Set(selectedTools.map((tool) => tool.id))],
        });
        onInitialPromptConsumed?.();

        setText('');
        setMention(null);
        localStorage.removeItem(draftStorageKey);
        if (isAuthenticated && navigator.onLine) void deleteRemoteDraft().catch(() => undefined);
        setQuotes([]);
        clearFiles();
    };

    const handleKeyDown = (event) => {
        if (event.isComposing || event.nativeEvent?.isComposing) return;
        if (mention) {
            if (event.key === 'Escape') { event.preventDefault(); setMention(null); return; }
            if (suggestions.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
                event.preventDefault();
                setActiveSuggestion((index) => (index + (event.key === 'ArrowDown' ? 1 : -1) + suggestions.length) % suggestions.length);
                return;
            }
            if (suggestions.length && event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault(); selectTool(suggestions[activeSuggestion]?.id || suggestions[0].id); return;
            }
        }
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

    const addQuote = useCallback((quoteText) => {
        if (!quoteText) return;

        setQuotes((prev) => (
            prev.includes(quoteText) ? prev : [...prev, quoteText]
        ));
    }, []);

    const showQuoteButton = useCallback(
        (range, selectedText) => {
            if (!quoteButtonRef.current?.isConnected) {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'quote-action-button ui-selection-quote-button';
                document.body.appendChild(button);
                quoteButtonRef.current = button;
            }

            const rect = range.getBoundingClientRect();
            const button = quoteButtonRef.current;
            button.textContent = t('composer.quote');
            button.onclick = (event) => {
                event.preventDefault();
                event.stopPropagation();
                addQuote(selectedText);
                window.getSelection()?.removeAllRanges();
                hideQuoteButton();
            };
            button.style.position = 'fixed';
            button.style.display = 'block';
            button.style.zIndex = '10000';
            button.classList.add('visible');

            const viewportPadding = 8;
            const buttonWidth = button.offsetWidth || 120;
            const buttonHeight = button.offsetHeight || 32;
            const centeredLeft = rect.left + rect.width / 2 - buttonWidth / 2;
            const maxLeft = Math.max(viewportPadding, window.innerWidth - buttonWidth - viewportPadding);
            const preferredTop = rect.top - buttonHeight - viewportPadding;
            const fallbackTop = Math.min(
                rect.bottom + viewportPadding,
                window.innerHeight - buttonHeight - viewportPadding
            );

            button.style.left = `${Math.min(Math.max(centeredLeft, viewportPadding), maxLeft)}px`;
            button.style.top = `${Math.max(viewportPadding, preferredTop >= viewportPadding ? preferredTop : fallbackTop)}px`;
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
            const quoteButton = quoteButtonRef.current;
            quoteButton?.remove();
            if (quoteButtonRef.current === quoteButton) quoteButtonRef.current = null;
        };
    }, [handleMouseUp, hideQuoteButton]);

    const effectiveFileCount = fileUploadsEnabled ? files.length : 0;
    const hasContent = Boolean(messageText.trim() || effectiveFileCount > 0 || quotes.length > 0);
    const hasQuotes = quotes.length > 0;
    const sendButtonClass = isLoading ? 'stop-button' : 'send-mode-button';

    const sendButtonTitle = isLoading
        ? t('composer.stop')
        : settings.requireCtrlEnterToSend
          ? t('composer.sendCtrlEnter')
          : t('composer.sendEnter');

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
                    <div className="drop-zone-subtext text-sm text-muted">
                        {t('composer.dragDropSubtitle', {
                            size: formatFileSize(CHAT_UPLOAD_MAX_TOTAL_BYTES, 0),
                        })}
                    </div>
                </div>
            </div>

            <footer
                ref={composerRef}
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
                    accept={CHAT_UPLOAD_ACCEPT}
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
                                className="attach-button ui-composer-icon-button"
                                title={t('composer.attachFiles')}
                                aria-label={t('composer.attachFiles')}
                                onClick={() => fileInputRef.current?.click()}
                            />
                        ) : (
                            <button
                                type="button"
                                className="attach-button ui-composer-icon-button cursor-not-allowed opacity-50"
                                title={isReadOnly ? t('composer.attachUnavailableReadOnly') : t('composer.attachRequiresAccount')}
                                aria-label={t('composer.attachUnavailable')}
                                onClick={(event) => {
                                    event.preventDefault();
                                    if (!isReadOnly && onOpenAuth) onOpenAuth();
                                }}
                            />
                        )}

                        <div className="composer-editor">
                            <ComposerTextEditor
                                ref={textareaRef}
                                value={text}
                                tools={editorTools}
                                placeholder={isReadOnly ? t('composer.placeholderReadOnly') : t('composer.placeholder')}
                                label={t('composer.ariaInput')}
                                descriptionId={showDynamicWarning && dynamicWarning ? 'dynamicWarningLabel' : undefined}
                                readOnly={isReadOnly}
                                onChange={(value, caret) => { setText(value); updateMention(value, caret); }}
                                onSelection={updateMention}
                                menuId={mention ? toolMenuId : undefined}
                                activeOptionId={mention && suggestions.length ? `${toolMenuId}-${activeSuggestion}` : undefined}
                                onBlur={() => setMention(null)}
                                onKeyDown={handleKeyDown}
                                onPaste={handlePaste}
                                onHeightChange={(_height, unwrappedWidth) => {
                                    const row = composerRef.current?.querySelector<HTMLElement>('.ui-composer-input-row');
                                    if (!row) return;
                                    const controls = Array.from(row.children).filter((child) =>
                                        child.matches('.attach-button, .composer-model-selector, .send-button'));
                                    const controlsWidth = controls.reduce((sum, child) => sum + child.getBoundingClientRect().width, 0);
                                    const gap = parseFloat(getComputedStyle(row).columnGap) || 4;
                                    const compactWidth = row.clientWidth - controlsWidth - gap * controls.length - 8;
                                    composerRef.current?.style.setProperty('--composer-available-width', `${row.clientWidth}px`);
                                    setExpanded(row.clientWidth <= 640 || unwrappedWidth > compactWidth);
                                }}
                            />
                        </div>
                        {mention && !isReadOnly && <div id={toolMenuId} className="composer-tool-menu" role="listbox" aria-label={t('composer.tools.choose')}>
                            {suggestions.map((tool, index) => <button type="button" role="option" id={`${toolMenuId}-${index}`} key={tool.id}
                                aria-selected={index === activeSuggestion} aria-disabled={!tool.available} disabled={!tool.available} className="composer-tool-option"
                                onPointerDown={(event) => event.preventDefault()}
                                onMouseEnter={() => setActiveSuggestion(index)} onClick={() => selectTool(tool.id)}>
                                <svg className="composer-tool-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d={toolIconPath(tool.id)} /></svg>
                                <span className="composer-tool-copy"><span className="composer-tool-name">{tool.label}</span><span className="composer-tool-description">{tool.description}</span></span>
                            </button>)}
                            {suggestions.length === 0 && <div className="composer-tool-hint">{t('composer.tools.empty')}</div>}
                        </div>}

                        {models.length > 0 && onModelChange && onThinkingLevelChange && (
                            <ModelSelector
                                currentModel={currentModel}
                                models={models}
                                onModelChange={onModelChange}
                                thinkingLevel={thinkingLevel}
                                onThinkingLevelChange={onThinkingLevelChange}
                            />
                        )}

                        <button
                            id="sendButton"
                            type="button"
                            className={cn(
                                'send-button ui-composer-icon-button',
                                hasContent && !isLoading && 'is-ready',
                                sendButtonClass
                            )}
                            title={isReadOnly ? t('chat.readOnly') : sendButtonTitle}
                            aria-label={isLoading ? t('composer.stop') : sendButtonTitle}
                            onClick={handleSend}
                            disabled={isReadOnly || (!isLoading && !hasContent)}
                        >
                        </button>
                    </div>
                </div>
            </footer>
        </>
    );
};

export default InputArea;
