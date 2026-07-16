import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Copy, Download, Eye, MessageSquare, PanelRightClose } from 'lucide-react';
import type { CanvasTextdoc } from '../../services/api';
import CanvasCodeEditor from './CanvasCodeEditor';

type CanvasPanelProps = {
    textdoc: CanvasTextdoc;
    onClose: () => void;
    onContentChange?: (content: string) => void;
    onDraftChange?: (content: string) => void;
    isPreviewActive?: boolean;
    onPreviewToggle?: () => void;
};

const codeTypePrefix = 'code/';
const CANVAS_COMMIT_DELAY_MS = 180;

function buildDownloadName(textdoc: CanvasTextdoc): string {
    const safeName = (textdoc.name || 'canvas')
        .replace(/[^a-z0-9_.-]+/gi, '-')
        .replace(/^-+|-+$/g, '')
        || 'canvas';
    const language = textdoc.type.startsWith(codeTypePrefix)
        ? textdoc.type.slice(codeTypePrefix.length)
        : 'txt';
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
    isPreviewActive = false,
    onPreviewToggle,
}: CanvasPanelProps) => {
    const { t } = useTranslation();
    const [copyState, setCopyState] = useState<'idle' | 'done'>('idle');
    const [draft, setDraft] = useState(textdoc.content || '');
    const pendingDraftRef = useRef(textdoc.content || '');
    const lastCommittedDraftRef = useRef(textdoc.content || '');
    const commitTimerRef = useRef<number | null>(null);
    const isCode = textdoc.type.startsWith(codeTypePrefix);
    const language = isCode ? textdoc.type.slice(codeTypePrefix.length) : '';
    const canPreviewHtml = textdoc.type === 'code/html';
    const comments = Array.isArray(textdoc.comments) ? textdoc.comments : [];
    const typeLabel = isCode
        ? t('canvas.type.code', { language })
        : t('canvas.type.document');

    const commitDraft = useCallback(() => {
        if (commitTimerRef.current !== null) {
            window.clearTimeout(commitTimerRef.current);
            commitTimerRef.current = null;
        }
        const content = pendingDraftRef.current;
        if (content === lastCommittedDraftRef.current) return;
        lastCommittedDraftRef.current = content;
        onContentChange?.(content);
    }, [onContentChange]);

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
        onDraftChange?.(content);
        if (commitTimerRef.current !== null) {
            window.clearTimeout(commitTimerRef.current);
        }
        commitTimerRef.current = window.setTimeout(commitDraft, CANVAS_COMMIT_DELAY_MS);
    };

    const handleClose = () => {
        commitDraft();
        onClose();
    };

    return (
        <aside className="chat-canvas-panel" aria-label={t('canvas.ariaLabel')}>
            <header className="chat-canvas-header">
                <div className="chat-canvas-title-block">
                    <strong title={textdoc.name}>{textdoc.name}</strong>
                    <span className="chat-canvas-type-label">{typeLabel}</span>
                </div>
                <div className="chat-canvas-header-actions">
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

            <div className="chat-canvas-body ui-scrollbar-thin">
                {isCode ? (
                    <div className="chat-canvas-code-editor">
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
                    </div>
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
