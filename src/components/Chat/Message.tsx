import React, { useEffect, useRef, useState, useMemo } from 'react';
import { formatText, formatPlainText, formatUserText, highlightCode } from '../../utils/formatting';
import { apiService } from '../../services/api';
import { fileService } from '../../services/fileService';
import Quiz from '../Widgets/Quiz';
import Spinwheel from '../Widgets/Spinwheel';
import Beatbox from '../Widgets/Beatbox';
import ThinkBlock from '../Widgets/ThinkBlock';
import { useAudio } from '../../hooks/useAudio';
import { Utils } from '../../utils/utils';
import TranslationPanel from './TranslationPanel';
import { useSettings } from '../../context/SettingsContext';

const Message = ({ message, onRegenerate, onEdit, onSwitchVariant }) => {
    const { role, content, images, files, isLoading, isError, isGeneratingImage, imagePrompt, widgetUpdate, variants, currentVariantIndex, parts } = message;
    const isUser = role === 'user';
    const { settings } = useSettings();
    const [isEditingUserMessage, setIsEditingUserMessage] = useState(false);
    const [editedContent, setEditedContent] = useState(content);
    const currentVariant = variants && variants.length > 0 && currentVariantIndex !== undefined
        ? variants[currentVariantIndex]
        : null;
    const filesFromParts = useMemo(() => {
        if (files && files.length > 0) return files;
        if (!parts || !Array.isArray(parts)) return [];
        return parts.filter(p => p.file).map(p => ({
            file: {
                url_path: p.file.url_path || p.file,
                original_name: p.file.original_name || p.file.name || 'file',
                mime_type: p.file.mime_type || 'application/octet-stream',
                size: p.file.size || 0
            }
        }));
    }, [files, parts]);
    const imagesFromParts = useMemo(() => {
        if (images && images.length > 0) return images;
        if (!parts || !Array.isArray(parts)) return [];
        return parts.filter(p => p.image).map(p => p.image.url_path || p.image);
    }, [images, parts]);

    let displayContent = currentVariant ? currentVariant.content : content;
    if (displayContent) {
        displayContent = displayContent.replace(/\{[^{}]*"url_path"[^{}]*\}/g, '');
        displayContent = displayContent.replace(/\{[^{}]*"original_name"[^{}]*\}/g, '');
        displayContent = displayContent.replace(/---\s*File:\s*[^-\n]+---[\s\S]*?---\s*End\s*File\s*---/gi, '');
        displayContent = displayContent.replace(/\[Binary\s+file:[^\]]+\]/gi, '');
        displayContent = displayContent.trim();
    }

    const displayImages = currentVariant ? (currentVariant.images || []) : imagesFromParts;
    const displayFiles = filesFromParts;
    const hasMultipleVariants = variants && variants.length > 1;
    const contentRef = useRef(null);
    const waveformCanvasRef = useRef(null);
    const [widgets, setWidgets] = useState([]);
    const [showTranslation, setShowTranslation] = useState(false);
    const audio = useAudio(message.id);
    useEffect(() => {
        if (!isUser) {
            const newWidgets = [];
            const fromBase64 = (str) => {
                try {
                    return decodeURIComponent(escape(atob(str)));
                } catch (e) {
                    console.warn('Base64 decoding failed:', e);
                    return str;
                }
            };
            if (parts && Array.isArray(parts)) {
                parts.forEach((part, partIdx) => {
                    if (part.text && typeof part.text === 'string') {
                        const text = part.text;
                        const beatboxRegex = /<beatbox>([\s\S]*?)<\/beatbox>/gi;
                        let beatboxMatch;
                        let beatboxIdx = 0;
                        while ((beatboxMatch = beatboxRegex.exec(text)) !== null) {
                            try {
                                const state = JSON.parse(beatboxMatch[1].trim());
                                newWidgets.push({
                                    type: 'beatbox',
                                    id: `beatbox-${message.id}-${partIdx}-${beatboxIdx}`,
                                    state
                                });
                                beatboxIdx++;
                            } catch (e) {
                                console.warn('Failed to parse beatbox from parts', e, beatboxMatch[1]);
                            }
                        }
                        const quizRegex = /<quiz>([\s\S]*?)<\/quiz>/gi;
                        let quizMatch;
                        let quizIdx = 0;
                        while ((quizMatch = quizRegex.exec(text)) !== null) {
                            try {
                                const state = JSON.parse(quizMatch[1].trim());
                                newWidgets.push({
                                    type: 'quiz',
                                    id: `quiz-${message.id}-${partIdx}-${quizIdx}`,
                                    state
                                });
                                quizIdx++;
                            } catch (e) {
                                console.warn('Failed to parse quiz from parts', e, quizMatch[1]);
                            }
                        }
                        const spinwheelRegex = /<spinwheel>([\s\S]*?)<\/spinwheel>/gi;
                        let spinwheelMatch;
                        let spinwheelIdx = 0;
                        while ((spinwheelMatch = spinwheelRegex.exec(text)) !== null) {
                            try {
                                const state = JSON.parse(spinwheelMatch[1].trim());
                                newWidgets.push({
                                    type: 'spinwheel',
                                    id: `spinwheel-${message.id}-${partIdx}-${spinwheelIdx}`,
                                    state
                                });
                                spinwheelIdx++;
                            } catch (e) {
                                console.warn('Failed to parse spinwheel from parts', e, spinwheelMatch[1]);
                            }
                        }
                        const thinkRegex = /<think(?:\s+data-open="(\d+)")?(?:\s+data-close="(\d+)")?>([\s\S]*?)<\/think>/gi;
                        let thinkMatch;
                        let thinkIdx = 0;
                        while ((thinkMatch = thinkRegex.exec(text)) !== null) {
                            try {
                                const openTime = thinkMatch[1] ? parseInt(thinkMatch[1], 10) : Date.now();
                                const closeTime = thinkMatch[2] ? parseInt(thinkMatch[2], 10) : Date.now();
                                const content = thinkMatch[3].trim();
                                newWidgets.push({
                                    type: 'think',
                                    id: `think-${message.id}-${partIdx}-${thinkIdx}`,
                                    content,
                                    openTime,
                                    closeTime
                                });
                                thinkIdx++;
                            } catch (e) {
                                console.warn('Failed to parse think from parts', e, thinkMatch[0]);
                            }
                        }
                    }
                });
            }
            if (contentRef.current && displayContent) {
                const beatboxHosts = contentRef.current.querySelectorAll('.beatbox-instance-host');
                const quizHosts = contentRef.current.querySelectorAll('.quiz-instance-host');
                const spinwheelHosts = contentRef.current.querySelectorAll('.spinwheel-instance-host');
                const thinkHosts = contentRef.current.querySelectorAll('.think-instance-host');

                beatboxHosts.forEach((host, idx) => {
                    let stateJson = host.getAttribute('data-beatbox-state-b64') || host.getAttribute('data-beatbox-state');
                    if (stateJson) {
                        try {
                            if (host.getAttribute('data-beatbox-state-b64')) {
                                stateJson = fromBase64(stateJson);
                            }
                            const state = JSON.parse(stateJson);
                            const existingId = `beatbox-${message.id}-${idx}`;
                            if (!newWidgets.some(w => w.id === existingId)) {
                                newWidgets.push({
                                    type: 'beatbox',
                                    id: existingId,
                                    state
                                });
                            }
                        } catch (e) {
                            console.warn('Failed to parse beatbox state', e, stateJson);
                        }
                    }
                });

                quizHosts.forEach((host, idx) => {
                    let stateJson = host.getAttribute('data-quiz-state-b64') || host.getAttribute('data-quiz-state');
                    if (stateJson) {
                        try {
                            if (host.getAttribute('data-quiz-state-b64')) {
                                stateJson = fromBase64(stateJson);
                            }
                            const state = JSON.parse(stateJson);
                            const existingId = `quiz-${message.id}-${idx}`;
                            if (!newWidgets.some(w => w.id === existingId)) {
                                newWidgets.push({
                                    type: 'quiz',
                                    id: existingId,
                                    state
                                });
                            }
                        } catch (e) {
                            console.warn('Failed to parse quiz state', e, stateJson);
                        }
                    }
                });

                spinwheelHosts.forEach((host, idx) => {
                    let stateJson = host.getAttribute('data-spinwheel-state-b64') || host.getAttribute('data-spinwheel-state');
                    if (stateJson) {
                        try {
                            if (host.getAttribute('data-spinwheel-state-b64')) {
                                stateJson = fromBase64(stateJson);
                            }
                            const state = JSON.parse(stateJson);
                            const existingId = `spinwheel-${message.id}-${idx}`;
                            if (!newWidgets.some(w => w.id === existingId)) {
                                newWidgets.push({
                                    type: 'spinwheel',
                                    id: existingId,
                                    state
                                });
                            }
                        } catch (e) {
                            console.warn('Failed to parse spinwheel state', e, stateJson);
                        }
                    }
                });

                thinkHosts.forEach((host, idx) => {
                    const openTime = host.getAttribute('data-think-open');
                    const closeTime = host.getAttribute('data-think-close');
                    const content = host.getAttribute('data-think-content');
                    if (content && openTime && closeTime) {
                        const existingId = `think-${message.id}-${idx}`;
                        if (!newWidgets.some(w => w.id === existingId)) {
                            newWidgets.push({
                                type: 'think',
                                id: existingId,
                                content,
                                openTime: parseInt(openTime, 10),
                                closeTime: parseInt(closeTime, 10)
                            });
                        }
                    }
                });
                beatboxHosts.forEach(host => {
                    if (!host.hasAttribute('data-from-parts')) {
                        host.remove();
                    }
                });
                quizHosts.forEach(host => {
                    if (!host.hasAttribute('data-from-parts')) {
                        host.remove();
                    }
                });
                spinwheelHosts.forEach(host => {
                    if (!host.hasAttribute('data-from-parts')) {
                        host.remove();
                    }
                });
                thinkHosts.forEach(host => {
                    if (!host.hasAttribute('data-from-parts')) {
                        host.remove();
                    }
                });
            }
            setTimeout(() => {
                setWidgets(newWidgets);
            }, 0);
        }
    }, [displayContent, isUser, message.id, parts]);
    useEffect(() => {
        if (widgetUpdate && !isUser) {
            const { tag, state } = widgetUpdate;
            try {
                let widgetState = state;
                if (typeof state === 'string') {
                    try {
                        widgetState = JSON.parse(state);
                    } catch {
                        widgetState = state;
                    }
                }
                setTimeout(() => {
                    setWidgets(prev => {
                        const existingIndex = prev.findLastIndex(w => w.type === tag);
                        if (existingIndex !== -1) {
                            return prev.map((w, idx) =>
                                idx === existingIndex
                                    ? { ...w, state: widgetState }
                                    : w
                            );
                        } else {
                            return [...prev, {
                                type: tag,
                                id: `${tag}-${message.id}-${Date.now()}`,
                                state: widgetState
                            }];
                        }
                    });
                }, 0);
            } catch (error) {
                console.warn('Failed to update widget', error);
            }
        }
    }, [widgetUpdate, message.id, isUser]);

    const markdownEnabledForMessage = isUser ? !!settings.renderUserMarkdown : !!settings.renderMarkdown;
    useEffect(() => {
        if (markdownEnabledForMessage && contentRef.current) {
            setTimeout(() => {
                if (window.Prism) {
                    window.Prism.highlightAllUnder(contentRef.current);
                } else {
                    highlightCode();
                }
                requestAnimationFrame(() => {
                    const codeBlocks = contentRef.current.querySelectorAll('pre.line-numbers');
                    codeBlocks.forEach(pre => {
                        if (window.Prism && window.Prism.plugins && window.Prism.plugins.lineNumbers) {
                            try {
                                if (!pre.querySelector('.line-numbers-rows')) {
                                    window.Prism.plugins.lineNumbers.resize(pre);
                                } else {
                                    window.Prism.plugins.lineNumbers.resize(pre);
                                }
                            } catch (e) {
                                console.warn('Failed to initialize line numbers:', e);
                            }
                        }
                    });
                });
                const codeBlockContents = contentRef.current.querySelectorAll('.code-block-content');
                codeBlockContents.forEach(content => {
                    if (!content.dataset.initialMaxHeight) {
                        const computedStyle = window.getComputedStyle(content);
                        const maxHeight = computedStyle.maxHeight || '200px';
                        content.dataset.initialMaxHeight = maxHeight;
                        content.style.maxHeight = maxHeight;
                    }
                    requestAnimationFrame(() => {
                        if (!content.classList.contains('expanded')) {
                            const initialMaxHeight = parseInt(content.dataset.initialMaxHeight || '200');
                            if (content.scrollHeight > initialMaxHeight) {
                                content.classList.add('has-overflow');
                            } else {
                                content.classList.remove('has-overflow');
                            }
                        }
                    });
                });
            }, 0);

            const renderVisuals = async () => {
                if (Utils.renderCharts) {
                    await Utils.renderCharts();
                }

                if (Utils.renderD3) {
                    await Utils.renderD3();
                }

                if (Utils.renderNomnoml) {
                    await Utils.renderNomnoml();
                }

                if (Utils.renderMermaid) {
                    await Utils.renderMermaid();
                }

                if (Utils.attachDiagramPan) {
                    Utils.attachDiagramPan();
                }
            };

            renderVisuals();
        }
    }, [displayContent, markdownEnabledForMessage, widgets]);
    useEffect(() => {
        if (!audio.isVisible || !waveformCanvasRef.current || !audio.waveformPoints) return;
        const canvas = waveformCanvasRef.current;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const { width, height } = canvas;
        ctx.clearRect(0, 0, width, height);
        const barWidth = width / audio.waveformPoints.length;
        const progressRatio = audio.totalDuration > 0 ? audio.currentTime / audio.totalDuration : 0;
        const progressPx = progressRatio * width;

        audio.waveformPoints.forEach((point, index) => {
            const x = index * barWidth;
            ctx.fillStyle = x < progressPx ? 'rgba(255, 255, 255, 0.9)' : 'rgba(255, 255, 255, 0.4)';
            ctx.fillRect(x, (height - point * height) / 2, Math.max(1, barWidth * 0.8), point * height);
        });
    }, [audio.isVisible, audio.currentTime, audio.totalDuration, audio.waveformPoints]);
    useEffect(() => {
        if (!markdownEnabledForMessage || !contentRef.current) return;

        const handleClick = (e) => {
            const target = e.target.closest('button');
            if (!target) return;

            if (target.classList.contains('table-copy-btn')) {
                e.preventDefault();
                const wrapper = target.closest('.table-wrapper');
                const table = wrapper?.querySelector?.('table');
                if (!table) return;

                const tableHtml = table.outerHTML;
                const blob = new Blob([tableHtml], { type: 'text/html' });

                const originalText = target.textContent;
                const applySuccessUI = () => {
                    target.textContent = '✓ Скопировано';
                    target.style.background = 'rgba(110, 231, 183, 0.15)';
                    setTimeout(() => {
                        target.textContent = originalText;
                        target.style.background = '';
                    }, 2000);
                };

                const applyErrorUI = () => {
                    target.textContent = 'Ошибка';
                    target.style.background = 'rgba(239, 68, 68, 0.15)';
                    setTimeout(() => {
                        target.textContent = originalText;
                        target.style.background = '';
                    }, 2000);
                };
                try {
                    if (navigator.clipboard?.write && typeof ClipboardItem !== 'undefined') {
                        const data = [new ClipboardItem({ 'text/html': blob })];
                        navigator.clipboard.write(data).then(applySuccessUI).catch(() => {
                            navigator.clipboard?.writeText?.(table.innerText || table.textContent || '').then(applySuccessUI).catch(applyErrorUI);
                        });
                    } else if (navigator.clipboard?.writeText) {
                        navigator.clipboard.writeText(table.innerText || table.textContent || '').then(applySuccessUI).catch(applyErrorUI);
                    } else {
                        applyErrorUI();
                    }
                } catch {
                    applyErrorUI();
                }
                return;
            }

            const codeBlock = target.closest('.code-block');
            if (!codeBlock) return;

            const codeElement = codeBlock.querySelector('code');
            if (!codeElement) return;

            const codeText = codeElement.textContent || '';

            if (target.classList.contains('code-tab-btn')) {
                const tab = target.dataset.tab;
                if (!tab) return;

                const tabs = codeBlock.querySelectorAll('.code-tab-btn');
                tabs.forEach(btn => btn.classList.toggle('active', btn === target));

                const panes = codeBlock.querySelectorAll('.code-block-pane');
                panes.forEach(pane => pane.classList.toggle('active', pane.dataset.pane === tab));

                if (tab === 'code') {
                    const content = codeBlock.querySelector('.code-block-content');
                    if (content) {
                        if (!content.dataset.initialMaxHeight) {
                            const computedStyle = window.getComputedStyle(content);
                            const maxHeight = computedStyle.maxHeight || '200px';
                            content.dataset.initialMaxHeight = maxHeight;
                            content.style.maxHeight = maxHeight;
                        }

                        requestAnimationFrame(() => {
                            if (!content.classList.contains('expanded')) {
                                const initialMaxHeight = parseInt(content.dataset.initialMaxHeight || '200', 10);
                                if (content.scrollHeight > initialMaxHeight) {
                                    content.classList.add('has-overflow');
                                } else {
                                    content.classList.remove('has-overflow');
                                }
                            }

                            const pre = content.querySelector('pre.line-numbers');
                            if (pre && window.Prism && window.Prism.plugins && window.Prism.plugins.lineNumbers) {
                                window.Prism.plugins.lineNumbers.resize(pre);
                            }
                        });
                    }
                }
            } else if (target.classList.contains('copy-code-btn')) {
                Utils.copyToClipboard(codeText, target);
            } else if (target.classList.contains('download-code-btn')) {
                const filename = codeBlock.dataset.filename || 'code.txt';
                const language = codeBlock.dataset.language || 'plaintext';
                const extension = language === 'plaintext' ? 'txt' : language;
                Utils.downloadFile(codeText, `${filename}.${extension}`, `text/${language}`);
            } else if (target.classList.contains('toggle-code-btn')) {
                const content = codeBlock.querySelector('.code-block-content');
                if (!content) return;

                const iconExpand = target.querySelector('.icon-expand');
                const iconCollapse = target.querySelector('.icon-collapse');
                const isCurrentlyCollapsed = !content.classList.contains('expanded');

                if (isCurrentlyCollapsed) {
                    content.classList.add('expanded');
                    target.classList.add('expanded');
                    target.title = "Свернуть";
                    content.style.maxHeight = content.scrollHeight + "px";
                    if (iconExpand) iconExpand.style.display = 'none';
                    if (iconCollapse) iconCollapse.style.display = 'block';
                    content.classList.remove('has-overflow');
                    requestAnimationFrame(() => {
                        const pre = content.querySelector('pre.line-numbers');
                        if (pre && window.Prism && window.Prism.plugins && window.Prism.plugins.lineNumbers) {
                            window.Prism.plugins.lineNumbers.resize(pre);
                        }
                    });
                } else {
                    content.classList.remove('expanded');
                    target.classList.remove('expanded');
                    target.title = "Развернуть";
                    const initialMaxHeight = content.dataset.initialMaxHeight || '200px';
                    content.style.maxHeight = initialMaxHeight;
                    if (iconExpand) iconExpand.style.display = 'block';
                    if (iconCollapse) iconCollapse.style.display = 'none';
                    setTimeout(() => {
                        if (content.scrollHeight > parseInt(initialMaxHeight)) {
                            content.classList.add('has-overflow');
                        } else {
                            content.classList.remove('has-overflow');
                        }
                    }, 100);
                }
            }
        };

        const currentRef = contentRef.current;
        if (currentRef) {
            currentRef.addEventListener('click', handleClick);
            return () => {
                currentRef.removeEventListener('click', handleClick);
            };
        }
    }, [displayContent, markdownEnabledForMessage]);
    const handleCopy = async () => {
        const contentToCopy = isUser ? content : displayContent;
        if (!contentToCopy) return;
        try {
            await navigator.clipboard.writeText(contentToCopy);
        } catch (e) {
            console.error('Failed to copy', e);
        }
    };
    const handleSaveEdit = () => {
        if (editedContent.trim() !== content && editedContent.trim()) {
            onEdit(message.id, editedContent.trim());
        }
        setIsEditingUserMessage(false);
    };
    const handleCancelEdit = () => {
        setEditedContent(content);
        setIsEditingUserMessage(false);
    };
    const htmlContent = useMemo(() => {
        if (isUser) {
            return markdownEnabledForMessage ? formatUserText(content || '') : formatPlainText(content || '');
        }
        return markdownEnabledForMessage ? formatText(displayContent || '') : formatPlainText(displayContent || '');
    }, [displayContent, isUser, content, markdownEnabledForMessage]);

    return (
        <div className={`message ${isUser ? 'user-message' : 'ai-message'} ${isLoading ? 'loading' : ''} ${isError ? 'error' : ''}`} data-message-id={message.id}>
            <div className="message-content">
                {}
                {(displayImages?.length > 0 || displayFiles?.length > 0) && (
                    <div className={`message-attachments ${isUser ? 'user-attachments' : 'ai-attachments'}`}>
                        {displayImages?.map((src, idx) => {
                            const fullSrc = src.startsWith('http') ? src : `${apiService.baseURL}${src}`;
                            return (
                                <img
                                    key={idx}
                                    className="attached-img"
                                    src={fullSrc}
                                    alt="attachment"
                                    onClick={() => {
                                        if (!isUser && window.openImageLightbox) {
                                            window.openImageLightbox(fullSrc, message.id);
                                        }
                                    }}
                                    style={{ cursor: !isUser ? 'pointer' : 'default' }}
                                />
                            );
                        })}
                        {displayFiles?.map((f, idx) => {
                            const file = f.file || f;
                            if (!file || typeof file === 'string' || (!file.url_path && !file.original_name && !file.name)) {
                                return null;
                            }

                            const fileName = file.original_name || file.name || 'File';
                            const fileUrl = file.url_path || '';
                            const fullUrl = fileUrl.startsWith('http') ? fileUrl : (fileUrl ? `${apiService.baseURL}${fileUrl}` : '');
                            const fileSize = file.size ? fileService.formatFileSize(file.size) : '';
                            const ext = fileName.split('.').pop()?.toLowerCase() || '';
                            const iconPath = fileService.getFileIconPath(ext);
                            const isImage = file.mime_type && fileService.VALID_IMAGE_MIME_TYPES.includes(file.mime_type) ||
                                          (ext && ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext));

                            return (
                                <div key={idx} className="attachment-file-card" title={`${fileName}${fileSize ? ` (${fileSize})` : ''}`}>
                                    <div className="attachment-card-preview">
                                        {isImage && fullUrl ? (
                                            <img
                                                src={fullUrl}
                                                alt={fileName}
                                                className="image-thumbnail"
                                                onClick={() => {
                                                    if (!isUser && window.openImageLightbox) {
                                                        window.openImageLightbox(fullUrl, message.id);
                                                    }
                                                }}
                                                style={{ cursor: !isUser ? 'pointer' : 'default' }}
                                                onError={(e) => {
                                                    e.target.src = iconPath;
                                                    e.target.className = 'generic-icon';
                                                }}
                                            />
                                        ) : (
                                            <img
                                                src={iconPath}
                                                alt={fileName}
                                                className="generic-icon"
                                                onError={(e) => e.target.src = 'https://cdn.jsdelivr.net/gh/vscode-icons/vscode-icons/icons/default_file.svg'}
                                            />
                                        )}
                                    </div>
                                    <div className="attachment-card-footer">
                                        <img
                                            src={iconPath}
                                            alt="icon"
                                            className="attachment-card-footer-icon"
                                            onError={(e) => e.target.src = 'https://cdn.jsdelivr.net/gh/vscode-icons/vscode-icons/icons/default_file.svg'}
                                        />
                                        <div className="attachment-card-footer-info">
                                            {fullUrl ? (
                                                <a
                                                    href={fullUrl}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className="file-card-name"
                                                    onClick={(e) => e.stopPropagation()}
                                                >
                                                    {fileService.escapeHtml(fileName)}
                                                </a>
                                            ) : (
                                                <span className="file-card-name">{fileService.escapeHtml(fileName)}</span>
                                            )}
                                            {fileSize && <span className="file-card-size">{fileSize}</span>}
                                        </div>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}

                {}
                {isGeneratingImage && (
                    <div className="image-generation-placeholder">
                        <div className="image-placeholder-visual">
                            <div className="shimmer-effect"></div>
                            <svg className="placeholder-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                                <polyline points="17 8 12 3 7 8"/>
                                <line x1="12" x2="12" y1="3" y2="15"/>
                            </svg>
                        </div>
                        <div className="image-placeholder-caption">
                            Создание изображения: <span>"{imagePrompt || ''}"</span>
                        </div>
                    </div>
                )}

                {}
                <div
                    ref={contentRef}
                    className="message-text"
                    dangerouslySetInnerHTML={{ __html: htmlContent }}
                />

                {}
                {widgets.map(widget => {
                    if (widget.type === 'quiz') {
                        return <Quiz key={widget.id} initialState={widget.state} />;
                    } else if (widget.type === 'spinwheel') {
                        return <Spinwheel key={widget.id} initialState={widget.state} />;
                    } else if (widget.type === 'beatbox') {
                        return <Beatbox key={widget.id} initialState={widget.state} />;
                    } else if (widget.type === 'think') {
                        return (
                            <ThinkBlock
                                key={widget.id}
                                content={widget.content}
                                openTime={widget.openTime}
                                closeTime={widget.closeTime}
                            />
                        );
                    }
                    return null;
                })}

                {}
                {isLoading && !displayContent && !isGeneratingImage && (
                    <div className="live-thinking-animation">
                        <div className="thinking-loader-wrapper">
                            <img src="/icons/load.svg" alt="Loading" className="thinking-loader-icon" />
                            <div className="thinking-phrase active">Думаю...</div>
                        </div>
                    </div>
                )}

                {}
                {!isUser && hasMultipleVariants && (
                    <div className="variants-nav">
                        <button
                            className="variant-btn prev-btn"
                            title="Предыдущий ответ"
                            disabled={currentVariantIndex <= 0}
                            onClick={() => onSwitchVariant && onSwitchVariant(message.id, -1)}
                        >
                            <img src="/icons/media/prev.svg" alt="<" />
                        </button>
                        <span className="variants-counter">
                            {(currentVariantIndex || 0) + 1}/{variants.length}
                        </span>
                        <button
                            className="variant-btn next-btn"
                            title="Следующий ответ"
                            disabled={(currentVariantIndex || 0) >= variants.length - 1}
                            onClick={() => onSwitchVariant && onSwitchVariant(message.id, 1)}
                        >
                            <img src="/icons/media/next.svg" alt=">" />
                        </button>
                    </div>
                )}

                {}
                {!isUser && !isLoading && (
                    <div className="actions-bar">
                        <button
                            className="action-btn copy-md-btn"
                            title="Копировать"
                            onClick={handleCopy}
                        >
                            <img src="/icons/ui/copy.svg" alt="Copy" />
                        </button>
                        <button
                            className={`action-btn speak-btn ${audio.isVisible ? 'active' : ''} ${audio.isLoading ? 'loading' : ''} ${audio.isError ? 'error' : ''}`}
                            title="Озвучить"
                            onClick={() => {
                                if (displayContent) {
                                    audio.speak(displayContent);
                                }
                            }}
                        >
                            <img src="/icons/media/audio.svg" alt="Speak" />
                        </button>
                        {onRegenerate && (
                            <button
                                className="action-btn regenerate-btn"
                                title="Регенерировать"
                                onClick={() => onRegenerate(message.id)}
                            >
                                <img src="/icons/ui/regenerate.svg" alt="Regenerate" />
                            </button>
                        )}
                        <button
                            className="action-btn translate-btn"
                            title="Перевести"
                            onClick={() => {
                                const textToTranslate = contentRef.current?.textContent?.trim() || displayContent || '';
                                if (textToTranslate) {
                                    setShowTranslation(true);
                                } else {
                                    Utils.showPopupWarning?.('Нет текста для перевода.');
                                }
                            }}
                        >
                        <img src="/icons/ui/translate.svg" alt="Translate" />
                        </button>
                    </div>
                )}

                {}
                {!isUser && showTranslation && (
                    <TranslationPanel
                        originalText={content || ''}
                        onClose={() => setShowTranslation(false)}
                    />
                )}

                {}
                {!isUser && audio.isVisible && (
                    <div className={`audio-player-container ${audio.isPlaying ? 'playing' : ''} visible`}>
                        <div className="audio-player-header">
                            <div className="audio-player-icon">
                                <svg width="18" height="18" viewBox="0 0 24 24">
                                    <path d="M12 4V20M8 8V16M16 7V17M4 10V14M20 9V15" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
                                </svg>
                                <span>Аудио</span>
                            </div>
                            {audio.isLoading && (
                                <div className="audio-player-loader">Загрузка аудио...</div>
                            )}
                        </div>
                        {!audio.isLoading && (
                            <div className="audio-player-controls" style={{ display: 'flex' }}>
                                <button
                                    className="audio-play-pause-btn"
                                    title={audio.isPlaying ? "Пауза" : "Воспроизвести"}
                                    onClick={audio.togglePlayback}
                                >
                                    <svg className="play-pause-icon" width="18" height="18" viewBox="0 0 24 24">
                                        {audio.isPlaying ? (
                                            <path className="pause-icon" d="M8 5V19M16 5V19" stroke="currentColor" strokeWidth="2"/>
                                        ) : (
                                            <path className="play-icon" d="M5 3l14 9-14 9z" stroke="currentColor" strokeWidth="2" fill="currentColor"/>
                                        )}
                                    </svg>
                                </button>
                                <div className="audio-waveform-container">
                                    <canvas ref={waveformCanvasRef} className="audio-waveform" height="48" width="200"></canvas>
                                    <input
                                        type="range"
                                        className="audio-progress-bar"
                                        min="0"
                                        max={audio.totalDuration || 1}
                                        value={audio.currentTime}
                                        step="0.1"
                                        onChange={(e) => audio.seekAudio(parseFloat(e.target.value))}
                                    />
                                </div>
                                <div className="audio-time">
                                    {audio.formatTime(audio.currentTime)} / {audio.formatTime(audio.totalDuration)}
                                </div>
                            </div>
                        )}
                        {audio.isError && (
                            <div className="audio-error-message" style={{ display: 'block' }}>
                                Ошибка: Не удалось загрузить аудио.
                            </div>
                        )}
                    </div>
                )}

                {}
                {isUser && onEdit && !isLoading && !isEditingUserMessage && (
                    <div className="actions-bar">
                        <button
                            className="action-btn copy-btn"
                            title="Копировать"
                            onClick={handleCopy}
                        >
                            <img src=" /icons/ui/copy.svg" alt="Copy" />
                        </button>
                        <button
                            className="action-btn edit-btn"
                            title="Редактировать"
                            onClick={() => setIsEditingUserMessage(true)}
                        >
                            <img src=" /icons/ui/edit.svg" alt="Edit" />
                        </button>
                    </div>
                )}

                {}
                {isUser && isEditingUserMessage && (
                    <div className="user-message-edit-panel">
                        <textarea
                            className="user-message-edit-textarea"
                            value={editedContent}
                            onChange={(e) => setEditedContent(e.target.value)}
                            placeholder="Отредактируйте ваше сообщение..."
                        />
                        <div className="edit-panel-buttons">
                            <button
                                className="edit-save-btn"
                                onClick={handleSaveEdit}
                                disabled={!editedContent.trim() || editedContent.trim() === content}
                            >
                                Сохранить
                            </button>
                            <button
                                className="edit-cancel-btn"
                                onClick={handleCancelEdit}
                            >
                                Отмена
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default Message;
