import {
    Fragment,
    useCallback,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
    type CSSProperties,
    type KeyboardEvent as ReactKeyboardEvent,
    type PointerEvent as ReactPointerEvent,
    type ReactNode,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Braces, Copy, Download, Eye, FileText, LoaderCircle, MessageSquare, PanelRightClose, Play, Terminal } from 'lucide-react';
import { apiService, type CanvasPythonExecutionResponse, type CanvasTextdoc } from '../../services/api';
import CanvasCodeEditor from './CanvasCodeEditor';
import CanvasMarkdownPreview from './CanvasMarkdownPreview';

type CanvasPanelProps = {
    textdoc: CanvasTextdoc;
    onClose: () => void;
    onContentChange?: (content: string) => void;
    onDraftChange?: (content: string) => void;
    onRepairPython?: (error: string, code: string) => void;
    isPreviewActive?: boolean;
    onPreviewToggle?: () => void;
    isStreaming?: boolean;
};

const codeTypePrefix = 'code/';
const CANVAS_COMMIT_DELAY_MS = 180;
const PYTHON_TERMINAL_MIN_HEIGHT = 128;
const PYTHON_TERMINAL_MAX_HEIGHT = 520;
const PYTHON_TERMINAL_DEFAULT_HEIGHT = 240;
const PYTHON_TERMINAL_RESIZE_STEP = 24;
type CanvasDocumentView = 'markdown' | 'raw';
type PythonRunState = 'idle' | 'running' | 'success' | 'error';

type PythonRun = {
    state: PythonRunState;
    result: CanvasPythonExecutionResponse | null;
    requestError: string;
};

const ANSI_COLOR_CLASSES: Record<number, string> = {
    30: 'chat-canvas-ansi-fg-black',
    31: 'chat-canvas-ansi-fg-red',
    32: 'chat-canvas-ansi-fg-green',
    33: 'chat-canvas-ansi-fg-yellow',
    34: 'chat-canvas-ansi-fg-blue',
    35: 'chat-canvas-ansi-fg-magenta',
    36: 'chat-canvas-ansi-fg-cyan',
    37: 'chat-canvas-ansi-fg-white',
    90: 'chat-canvas-ansi-fg-bright-black',
    91: 'chat-canvas-ansi-fg-bright-red',
    92: 'chat-canvas-ansi-fg-bright-green',
    93: 'chat-canvas-ansi-fg-bright-yellow',
    94: 'chat-canvas-ansi-fg-bright-blue',
    95: 'chat-canvas-ansi-fg-bright-magenta',
    96: 'chat-canvas-ansi-fg-bright-cyan',
    97: 'chat-canvas-ansi-fg-bright-white',
};

function renderAnsiText(value: string): ReactNode {
    const nodes: ReactNode[] = [];
    const ansiPattern = /\u001b\[([0-9;]*)m|\u001b(?:\[[0-?]*[ -/]*[@-~]|\][^\u0007]*(?:\u0007|\u001b\\))/g;
    let colorClass = '';
    let isBold = false;
    let lastIndex = 0;
    let match: RegExpExecArray | null;
    let partIndex = 0;

    const appendText = (text: string) => {
        if (!text) return;
        const classes = [colorClass, isBold ? 'chat-canvas-ansi-bold' : ''].filter(Boolean).join(' ');
        nodes.push(classes
            ? <span key={`ansi-${partIndex++}`} className={classes}>{text}</span>
            : <Fragment key={`ansi-${partIndex++}`}>{text}</Fragment>);
    };

    while ((match = ansiPattern.exec(value)) !== null) {
        appendText(value.slice(lastIndex, match.index));
        const codes = match[1] ? match[1].split(';').map(Number) : [];
        for (const code of codes) {
            if (code === 0) {
                colorClass = '';
                isBold = false;
            } else if (code === 1) {
                isBold = true;
            } else if (code === 22) {
                isBold = false;
            } else if (code === 39) {
                colorClass = '';
            } else if (ANSI_COLOR_CLASSES[code]) {
                colorClass = ANSI_COLOR_CLASSES[code];
            }
        }
        lastIndex = ansiPattern.lastIndex;
    }
    appendText(value.slice(lastIndex));
    return nodes;
}

const INITIAL_PYTHON_RUN: PythonRun = {
    state: 'idle',
    result: null,
    requestError: '',
};

function buildDownloadName(textdoc: CanvasTextdoc): string {
    const safeName = (textdoc.name || 'canvas')
        .replace(/[^a-z0-9_.-]+/gi, '-')
        .replace(/^-+|-+$/g, '')
        || 'canvas';
    const language = textdoc.type.startsWith(codeTypePrefix)
        ? textdoc.type.slice(codeTypePrefix.length)
        : 'document';
    const extension = language === 'javascript' ? 'js'
        : language === 'typescript' ? 'ts'
            : language === 'python' ? 'py'
                : language === 'html' ? 'html'
                    : language === 'document' ? 'md'
                        : language || 'txt';
    return `${safeName}.${extension}`;
}

const CanvasPanel = ({
    textdoc,
    onClose,
    onContentChange,
    onDraftChange,
    onRepairPython,
    isPreviewActive = false,
    onPreviewToggle,
    isStreaming = false,
}: CanvasPanelProps) => {
    const { t } = useTranslation();
    const [copyState, setCopyState] = useState<'idle' | 'done'>('idle');
    const [draft, setDraft] = useState(textdoc.content || '');
    const [documentView, setDocumentView] = useState<CanvasDocumentView>('markdown');
    const [pythonRun, setPythonRun] = useState<PythonRun>(INITIAL_PYTHON_RUN);
    const [pythonTerminalHeight, setPythonTerminalHeight] = useState(PYTHON_TERMINAL_DEFAULT_HEIGHT);
    const [isPythonTerminalResizing, setPythonTerminalResizing] = useState(false);
    const pendingDraftRef = useRef(textdoc.content || '');
    const lastCommittedDraftRef = useRef(textdoc.content || '');
    const commitTimerRef = useRef<number | null>(null);
    const onContentChangeRef = useRef(onContentChange);
    const onDraftChangeRef = useRef(onDraftChange);
    const pythonTerminalResizeRef = useRef<{
        pointerId: number;
        startY: number;
        startHeight: number;
    } | null>(null);
    const isCode = textdoc.type.startsWith(codeTypePrefix);
    const language = isCode ? textdoc.type.slice(codeTypePrefix.length) : '';
    const canPreviewHtml = textdoc.type === 'code/html';
    const isPython = isCode && ['python', 'py', 'python3'].includes(language.toLowerCase());
    const comments = Array.isArray(textdoc.comments) ? textdoc.comments : [];
    const typeLabel = isCode
        ? t('canvas.type.code', { language })
        : t('canvas.type.document');

    useLayoutEffect(() => {
        onContentChangeRef.current = onContentChange;
        onDraftChangeRef.current = onDraftChange;
    }, [onContentChange, onDraftChange]);

    const commitDraft = useCallback(() => {
        if (commitTimerRef.current !== null) {
            window.clearTimeout(commitTimerRef.current);
            commitTimerRef.current = null;
        }
        const content = pendingDraftRef.current;
        if (content === lastCommittedDraftRef.current) return;
        lastCommittedDraftRef.current = content;
        onContentChangeRef.current?.(content);
    }, []);

    useEffect(() => {
        const nextContent = textdoc.content || '';
        if (commitTimerRef.current !== null) {
            window.clearTimeout(commitTimerRef.current);
            commitTimerRef.current = null;
        }
        if (nextContent === pendingDraftRef.current) {
            lastCommittedDraftRef.current = nextContent;
            return;
        }
        const frame = window.requestAnimationFrame(() => {
            setDraft(nextContent);
            pendingDraftRef.current = nextContent;
            lastCommittedDraftRef.current = nextContent;
        });
        return () => window.cancelAnimationFrame(frame);
    }, [textdoc.id, textdoc.updated_at, textdoc.content]);

    useEffect(() => () => {
        if (commitTimerRef.current !== null) {
            window.clearTimeout(commitTimerRef.current);
        }
    }, []);

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(draft || '');
            setCopyState('done');
            window.setTimeout(() => setCopyState('idle'), 1400);
        } catch {
            setCopyState('idle');
        }
    };

    const handleDownload = () => {
        const blob = new Blob([draft || ''], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = buildDownloadName(textdoc);
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    };

    const handleDraftChange = (content: string) => {
        setDraft(content);
        pendingDraftRef.current = content;
        onDraftChangeRef.current?.(content);
        if (commitTimerRef.current !== null) {
            window.clearTimeout(commitTimerRef.current);
        }
        commitTimerRef.current = window.setTimeout(commitDraft, CANVAS_COMMIT_DELAY_MS);
    };

    const handleMarkdownDraftChange = useCallback((content: string) => {
        pendingDraftRef.current = content;
        onDraftChangeRef.current?.(content);
        if (commitTimerRef.current !== null) {
            window.clearTimeout(commitTimerRef.current);
        }
        commitTimerRef.current = window.setTimeout(commitDraft, CANVAS_COMMIT_DELAY_MS);
    }, [commitDraft]);

    const handleMarkdownBlur = useCallback((content: string) => {
        setDraft(content);
        pendingDraftRef.current = content;
        commitDraft();
    }, [commitDraft]);

    const handleClose = () => {
        commitDraft();
        onClose();
    };

    const handleRunPython = async () => {
        if (!isPython || !draft.trim() || pythonRun.state === 'running') return;
        setPythonRun({ state: 'running', result: null, requestError: '' });
        try {
            const result = await apiService.executeCanvasPython(draft);
            setPythonRun({
                state: result.ok ? 'success' : 'error',
                result,
                requestError: '',
            });
        } catch (error) {
            setPythonRun({
                state: 'error',
                result: null,
                requestError: error instanceof Error ? error.message : t('canvas.pythonTerminal.requestFailed'),
            });
        }
    };

    const pythonErrorText = pythonRun.requestError
        || pythonRun.result?.stderr
        || pythonRun.result?.error
        || (pythonRun.state === 'error' ? t('canvas.pythonTerminal.requestFailed') : '')
        || '';

    const handleRepairPython = () => {
        if (pythonRun.state !== 'error' || !pythonErrorText || !onRepairPython) return;
        onRepairPython(pythonErrorText, draft);
    };

    const handlePythonTerminalOutputKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
        if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'a') return;
        event.preventDefault();
        const selection = window.getSelection();
        if (!selection) return;
        const range = document.createRange();
        range.selectNodeContents(event.currentTarget);
        selection.removeAllRanges();
        selection.addRange(range);
    };

    const handlePythonTerminalResizeStart = (event: ReactPointerEvent<HTMLDivElement>) => {
        if (event.pointerType === 'mouse' && event.button !== 0) return;
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        pythonTerminalResizeRef.current = {
            pointerId: event.pointerId,
            startY: event.clientY,
            startHeight: pythonTerminalHeight,
        };
        setPythonTerminalResizing(true);
    };

    const handlePythonTerminalResizeMove = (event: ReactPointerEvent<HTMLDivElement>) => {
        const resizeState = pythonTerminalResizeRef.current;
        if (!resizeState || resizeState.pointerId !== event.pointerId) return;
        const nextHeight = resizeState.startHeight + resizeState.startY - event.clientY;
        setPythonTerminalHeight(Math.max(
            PYTHON_TERMINAL_MIN_HEIGHT,
            Math.min(PYTHON_TERMINAL_MAX_HEIGHT, nextHeight)
        ));
    };

    const handlePythonTerminalResizeEnd = (event: ReactPointerEvent<HTMLDivElement>) => {
        const resizeState = pythonTerminalResizeRef.current;
        if (!resizeState || resizeState.pointerId !== event.pointerId) return;
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
        }
        pythonTerminalResizeRef.current = null;
        setPythonTerminalResizing(false);
    };

    const handlePythonTerminalResizeKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
        let nextHeight = pythonTerminalHeight;
        if (event.key === 'ArrowUp') nextHeight += PYTHON_TERMINAL_RESIZE_STEP;
        if (event.key === 'ArrowDown') nextHeight -= PYTHON_TERMINAL_RESIZE_STEP;
        if (event.key === 'Home') nextHeight = PYTHON_TERMINAL_MIN_HEIGHT;
        if (event.key === 'End') nextHeight = PYTHON_TERMINAL_MAX_HEIGHT;
        if (nextHeight === pythonTerminalHeight) return;
        event.preventDefault();
        setPythonTerminalHeight(Math.max(
            PYTHON_TERMINAL_MIN_HEIGHT,
            Math.min(PYTHON_TERMINAL_MAX_HEIGHT, nextHeight)
        ));
    };

    return (
        <aside className="chat-canvas-panel" aria-label={t('canvas.ariaLabel')}>
            <header className="chat-canvas-header">
                <div className="chat-canvas-title-block">
                    <strong title={textdoc.name}>{textdoc.name}</strong>
                    <span className="chat-canvas-type-label">{typeLabel}</span>
                </div>
                <div className="chat-canvas-header-actions">
                    {!isCode && (
                        <div
                            className="chat-canvas-mode-actions"
                            role="tablist"
                            aria-label={t('canvas.mode.group')}
                        >
                            <button
                                type="button"
                                role="tab"
                                className={`chat-canvas-icon-button${documentView === 'markdown' ? ' is-active' : ''}`}
                                aria-selected={documentView === 'markdown'}
                                aria-label={t('canvas.mode.markdown')}
                                title={t('canvas.mode.markdown')}
                                onClick={() => setDocumentView('markdown')}
                                data-canvas-view="markdown"
                            >
                                <FileText size={16} aria-hidden="true" />
                            </button>
                            <button
                                type="button"
                                role="tab"
                                className={`chat-canvas-icon-button${documentView === 'raw' ? ' is-active' : ''}`}
                                aria-selected={documentView === 'raw'}
                                aria-label={t('canvas.mode.raw')}
                                title={t('canvas.mode.raw')}
                                onClick={() => setDocumentView('raw')}
                                data-canvas-view="raw"
                            >
                                <Braces size={16} aria-hidden="true" />
                            </button>
                        </div>
                    )}
                    {canPreviewHtml && (
                        <button
                            type="button"
                            className={`chat-canvas-icon-button${isPreviewActive ? ' is-active' : ''}`}
                            onClick={onPreviewToggle}
                            aria-pressed={isPreviewActive}
                            aria-label={t('canvas.preview')}
                            title={t('canvas.preview')}
                        >
                            <Eye size={16} />
                        </button>
                    )}
                    {isPython && (
                        <button
                            type="button"
                            className="chat-canvas-icon-button chat-canvas-python-run-header-button"
                            onClick={() => void handleRunPython()}
                            disabled={!draft.trim() || pythonRun.state === 'running'}
                            aria-label={t('canvas.pythonTerminal.run')}
                            title={t('canvas.pythonTerminal.run')}
                        >
                            {pythonRun.state === 'running'
                                ? <LoaderCircle size={16} className="chat-canvas-python-spinner" aria-hidden="true" />
                                : <Play size={16} fill="currentColor" aria-hidden="true" />}
                            <span>{t('canvas.pythonTerminal.run')}</span>
                        </button>
                    )}
                    <button
                        type="button"
                        className="chat-canvas-icon-button"
                        onClick={handleCopy}
                        aria-label={copyState === 'done' ? t('canvas.copied') : t('canvas.copy')}
                        title={copyState === 'done' ? t('canvas.copied') : t('canvas.copy')}
                    >
                        <Copy size={16} />
                    </button>
                    <button
                        type="button"
                        className="chat-canvas-icon-button"
                        onClick={handleDownload}
                        aria-label={t('canvas.download')}
                        title={t('canvas.download')}
                    >
                        <Download size={16} />
                    </button>
                    <button
                        type="button"
                        className="chat-canvas-icon-button chat-canvas-close-button"
                        onClick={handleClose}
                        aria-label={t('canvas.close')}
                        title={t('canvas.close')}
                    >
                        <PanelRightClose size={17} />
                    </button>
                </div>
            </header>

            <div className={`chat-canvas-body ui-scrollbar-thin${isCode ? ' is-code' : ' is-document'}`}>
                {isCode ? (
                    <div className="chat-canvas-code-workspace">
                        <div className={`chat-canvas-code-editor${isStreaming ? ' is-streaming' : ''}`}>
                            <CanvasCodeEditor
                                value={draft}
                                language={language}
                                filename={textdoc.name}
                                ariaLabel={t('canvas.editorLabel')}
                                emptyText={t('canvas.empty')}
                                collapseLabel={t('codeBlock.collapse')}
                                expandLabel={t('codeBlock.expand')}
                                onChange={handleDraftChange}
                                onBlur={commitDraft}
                            />
                            <div
                                className={`chat-canvas-code-stream-overlay${isStreaming ? ' is-active' : ''}`}
                                aria-hidden="true"
                            >
                                <span />
                            </div>
                        </div>
                        {isPython && (
                            <>
                                <div
                                    className={`chat-canvas-python-terminal-resize-handle${isPythonTerminalResizing ? ' is-resizing' : ''}`}
                                    role="separator"
                                    aria-orientation="horizontal"
                                    aria-label={t('canvas.pythonTerminal.resize')}
                                    aria-valuemin={PYTHON_TERMINAL_MIN_HEIGHT}
                                    aria-valuemax={PYTHON_TERMINAL_MAX_HEIGHT}
                                    aria-valuenow={pythonTerminalHeight}
                                    tabIndex={0}
                                    onPointerDown={handlePythonTerminalResizeStart}
                                    onPointerMove={handlePythonTerminalResizeMove}
                                    onPointerUp={handlePythonTerminalResizeEnd}
                                    onPointerCancel={handlePythonTerminalResizeEnd}
                                    onKeyDown={handlePythonTerminalResizeKeyDown}
                                />
                                <section
                                    className="chat-canvas-python-terminal"
                                    aria-label={t('canvas.pythonTerminal.ariaLabel')}
                                    aria-busy={pythonRun.state === 'running'}
                                    style={{ '--python-terminal-height': `${pythonTerminalHeight}px` } as CSSProperties}
                                >
                                <header className="chat-canvas-python-terminal-header">
                                    <div className="chat-canvas-python-terminal-title">
                                        <Terminal size={15} aria-hidden="true" />
                                        <span>{t('canvas.pythonTerminal.title')}</span>
                                        {pythonRun.state !== 'idle' && (
                                            <span className={`chat-canvas-python-terminal-status is-${pythonRun.state}`}>
                                                {pythonRun.state === 'running'
                                                    ? t('canvas.pythonTerminal.running')
                                                    : pythonRun.state === 'success'
                                                        ? t('canvas.pythonTerminal.success')
                                                        : t('canvas.pythonTerminal.failed')}
                                            </span>
                                        )}
                                        {pythonRun.result?.duration_ms !== undefined && (
                                            <span className="chat-canvas-python-terminal-meta">
                                                {t('canvas.pythonTerminal.duration', { duration: pythonRun.result.duration_ms })}
                                            </span>
                                        )}
                                    </div>
                                    {pythonRun.state === 'error' && pythonErrorText && onRepairPython && (
                                        <button
                                            type="button"
                                            className="chat-canvas-python-repair-button"
                                            onClick={handleRepairPython}
                                            aria-label={t('canvas.pythonTerminal.repair')}
                                        >
                                            {t('canvas.pythonTerminal.repair')}
                                        </button>
                                    )}
                                </header>
                                <div
                                    className="chat-canvas-python-terminal-output"
                                    aria-live="polite"
                                    tabIndex={0}
                                    onKeyDown={handlePythonTerminalOutputKeyDown}
                                    onMouseDown={(event) => event.currentTarget.focus()}
                                >
                                    {pythonRun.state === 'idle' ? (
                                        <span className="chat-canvas-python-terminal-placeholder">
                                            {t('canvas.pythonTerminal.empty')}
                                        </span>
                                    ) : pythonRun.requestError ? (
                                        <pre className="chat-canvas-python-terminal-stderr">{renderAnsiText(pythonRun.requestError)}</pre>
                                    ) : (
                                        <>
                                            {pythonRun.result?.stdout && <pre>{renderAnsiText(pythonRun.result.stdout)}</pre>}
                                            {pythonRun.result?.stderr && <pre className="chat-canvas-python-terminal-stderr">{renderAnsiText(pythonRun.result.stderr)}</pre>}
                                            {pythonRun.result?.error && !pythonRun.result.stderr && (
                                                <pre className="chat-canvas-python-terminal-stderr">{renderAnsiText(pythonRun.result.error)}</pre>
                                            )}
                                            {!pythonRun.result?.stdout && !pythonRun.result?.stderr && !pythonRun.result?.error && (
                                                pythonRun.state === 'error'
                                                    ? <pre className="chat-canvas-python-terminal-stderr">{renderAnsiText(pythonErrorText)}</pre>
                                                    : <span className="chat-canvas-python-terminal-placeholder">
                                                        {t('canvas.pythonTerminal.noOutput')}
                                                    </span>
                                            )}
                                        </>
                                    )}
                                </div>
                                </section>
                            </>
                        )}
                    </div>
                ) : (
                    <div className="chat-canvas-document">
                        <div className={`chat-canvas-document-content is-${documentView}`}>
                            {documentView === 'markdown' ? (
                                <CanvasMarkdownPreview
                                    content={draft}
                                    onChange={handleMarkdownDraftChange}
                                    onBlur={handleMarkdownBlur}
                                />
                            ) : (
                                <textarea
                                    className="chat-canvas-editor"
                                    value={draft}
                                    onChange={(event) => handleDraftChange(event.target.value)}
                                    onBlur={commitDraft}
                                    placeholder={t('canvas.empty')}
                                    aria-label={t('canvas.editorLabel')}
                                    spellCheck
                                />
                            )}
                        </div>
                    </div>
                )}
            </div>

            {comments.length > 0 && (
                <section className="chat-canvas-comments" aria-label={t('canvas.comments.title')}>
                    <div className="chat-canvas-comments-title">
                        <MessageSquare size={15} aria-hidden="true" />
                        <strong>{t('canvas.comments.title')}</strong>
                        <span>{t('canvas.comments.count', { count: comments.length })}</span>
                    </div>
                    <div className="chat-canvas-comment-list">
                        {comments.map((comment, index) => (
                            <article className="chat-canvas-comment" key={comment.id || `${comment.pattern}-${index}`}>
                                <code>{comment.pattern}</code>
                                <p>{comment.comment}</p>
                            </article>
                        ))}
                    </div>
                </section>
            )}
        </aside>
    );
};

export default CanvasPanel;
