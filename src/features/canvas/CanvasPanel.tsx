import { useEffect, useMemo, useRef, useState, type UIEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Copy, Download, Eye, MessageSquare, PanelRightClose } from 'lucide-react';
import DOMPurify from 'dompurify';
import Prism from 'prismjs';
import 'prismjs/components/prism-markup-templating';
import 'prismjs/components/prism-bash';
import 'prismjs/components/prism-c';
import 'prismjs/components/prism-cpp';
import 'prismjs/components/prism-csharp';
import 'prismjs/components/prism-diff';
import 'prismjs/components/prism-docker';
import 'prismjs/components/prism-git';
import 'prismjs/components/prism-go';
import 'prismjs/components/prism-java';
import 'prismjs/components/prism-json';
import 'prismjs/components/prism-jsx';
import 'prismjs/components/prism-markdown';
import 'prismjs/components/prism-php';
import 'prismjs/components/prism-powershell';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-ruby';
import 'prismjs/components/prism-rust';
import 'prismjs/components/prism-sql';
import 'prismjs/components/prism-typescript';
import 'prismjs/components/prism-tsx';
import 'prismjs/components/prism-yaml';
import type { CanvasTextdoc } from '../../services/api';

type CanvasPanelProps = {
    textdoc: CanvasTextdoc;
    onClose: () => void;
    onContentChange?: (content: string) => void;
};

type CanvasPreviewWindow = Window & {
    openHtmlPreviewModal?: (urlOrHtml: string, isHtml?: boolean) => void;
};

const codeTypePrefix = 'code/';

const canvasLanguageAliases: Record<string, string> = {
    'c++': 'cpp',
    'c#': 'csharp',
    html: 'markup',
    xml: 'markup',
    svg: 'markup',
    js: 'javascript',
    mjs: 'javascript',
    cjs: 'javascript',
    jsx: 'jsx',
    ts: 'typescript',
    mts: 'typescript',
    cts: 'typescript',
    tsx: 'tsx',
    py: 'python',
    rb: 'ruby',
    rs: 'rust',
    sh: 'bash',
    shell: 'bash',
    shellscript: 'bash',
    zsh: 'bash',
    ps1: 'powershell',
    psm1: 'powershell',
    md: 'markdown',
    yml: 'yaml',
    jsonc: 'json',
    dockerfile: 'docker',
    plaintext: 'none',
    text: 'none',
    txt: 'none',
};

const escapeHtml = (value: string) => value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');

function getCanvasPrismLanguage(language: string): string {
    const normalized = (language || 'plaintext').trim().toLowerCase().replace(/[^a-z0-9+#._-]/g, '').slice(0, 32);
    const prismLanguage = canvasLanguageAliases[normalized] || normalized || 'plaintext';
    return /^[a-z0-9_-]+$/.test(prismLanguage) ? prismLanguage : 'plaintext';
}

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

const CanvasPanel = ({ textdoc, onClose, onContentChange }: CanvasPanelProps) => {
    const { t } = useTranslation();
    const [copyState, setCopyState] = useState<'idle' | 'done'>('idle');
    const [draft, setDraft] = useState(textdoc.content || '');
    const lastSyncedDraftRef = useRef(textdoc.content || '');
    const highlightRef = useRef<HTMLPreElement | null>(null);
    const isCode = textdoc.type.startsWith(codeTypePrefix);
    const language = isCode ? textdoc.type.slice(codeTypePrefix.length) : '';
    const prismLanguage = useMemo(() => getCanvasPrismLanguage(language), [language]);
    const canPreviewHtml = textdoc.type === 'code/html';
    const comments = Array.isArray(textdoc.comments) ? textdoc.comments : [];
    const lineCount = useMemo(() => (draft || '').split(/\r\n|\r|\n/).length, [draft]);
    const typeLabel = isCode
        ? t('canvas.type.code', { language })
        : t('canvas.type.document');
    const highlightedCode = useMemo(() => {
        if (!isCode) {
            return '';
        }

        const displayCode = `${draft || ' '}${draft.endsWith('\n') ? ' ' : ''}`;
        const grammar = Prism.languages[prismLanguage];
        const highlighted = grammar
            ? Prism.highlight(displayCode, grammar, prismLanguage)
            : escapeHtml(displayCode);

        return DOMPurify.sanitize(highlighted);
    }, [draft, isCode, prismLanguage]);

    useEffect(() => {
        const nextContent = textdoc.content || '';
        setDraft(nextContent);
        lastSyncedDraftRef.current = nextContent;
    }, [textdoc.id, textdoc.updated_at, textdoc.content]);

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

    const handlePreview = () => {
        const previewWindow = window as CanvasPreviewWindow;
        if (canPreviewHtml && previewWindow.openHtmlPreviewModal) {
            previewWindow.openHtmlPreviewModal(draft || '', true);
        }
    };

    const handleDraftChange = (content: string) => {
        setDraft(content);
        lastSyncedDraftRef.current = content;
        onContentChange?.(content);
    };

    const handleEditorScroll = (event: UIEvent<HTMLTextAreaElement>) => {
        const highlightLayer = highlightRef.current;
        if (!highlightLayer) {
            return;
        }

        const target = event.currentTarget;
        highlightLayer.style.transform = `translate(${-target.scrollLeft}px, ${-target.scrollTop}px)`;
    };

    return (
        <aside className="chat-canvas-panel" aria-label={t('canvas.ariaLabel')}>
            <header className="chat-canvas-header">
                <div className="chat-canvas-title-block">
                    {/* <span className="chat-canvas-icon" aria-hidden="true">
                        {isCode ? <Code2 size={17} /> : <FileText size={17} />}
                    </span> */}
                    <div>
                        <strong title={textdoc.name}>{textdoc.name}</strong>
                    </div>
                </div>
                <button
                    type="button"
                    className="chat-canvas-icon-button"
                    onClick={onClose}
                    aria-label={t('canvas.close')}
                    title={t('canvas.close')}
                >
                    <PanelRightClose size={17} />
                </button>
            </header>

            <div className="chat-canvas-toolbar">
                <div className="chat-canvas-meta">
                    <span>{typeLabel}</span>
                    <span>{t('canvas.lines', { count: lineCount })}</span>
                </div>
                <div className="chat-canvas-actions">
                    {canPreviewHtml && (
                        <button
                            type="button"
                            className="chat-canvas-icon-button"
                            onClick={handlePreview}
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
                </div>
            </div>

            <div className="chat-canvas-body ui-scrollbar-thin">
                {isCode ? (
                    <div className="chat-canvas-code-editor">
                        <pre
                            ref={highlightRef}
                            className={`chat-canvas-highlight language-${prismLanguage}`}
                            aria-hidden="true"
                            dangerouslySetInnerHTML={{ __html: highlightedCode }}
                        />
                        <textarea
                            className="chat-canvas-editor is-code"
                            value={draft}
                            onChange={(event) => handleDraftChange(event.target.value)}
                            onScroll={handleEditorScroll}
                            placeholder={t('canvas.empty')}
                            aria-label={t('canvas.editorLabel')}
                            spellCheck={false}
                            autoCapitalize="off"
                            autoCorrect="off"
                        />
                    </div>
                ) : (
                    <textarea
                        className="chat-canvas-editor"
                        value={draft}
                        onChange={(event) => handleDraftChange(event.target.value)}
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
