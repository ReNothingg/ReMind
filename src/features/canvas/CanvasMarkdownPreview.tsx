import {
    memo,
    useCallback,
    useEffect,
    useLayoutEffect,
    useMemo,
    useRef,
    type ClipboardEvent as ReactClipboardEvent,
    type DragEvent as ReactDragEvent,
    type FocusEvent as ReactFocusEvent,
    type FormEvent,
    type MouseEvent as ReactMouseEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import { formatText, highlightCode, refreshCodeLineNumbers } from '../../utils/formatting';
import { renderedMarkdownToSource } from '../../utils/markdownDom';
import { Utils } from '../../utils/utils';

type CanvasMarkdownPreviewProps = {
    content: string;
    onChange: (content: string) => void;
    onBlur: (content: string) => void;
};

const insertPlainTextAtSelection = (text: string) => {
    const selection = window.getSelection();
    if (!selection?.rangeCount) return;
    const range = selection.getRangeAt(0);
    range.deleteContents();

    const fragment = document.createDocumentFragment();
    const parts = text.replace(/\r\n?/g, '\n').split('\n');
    parts.forEach((part, index) => {
        if (index > 0) fragment.appendChild(document.createElement('br'));
        fragment.appendChild(document.createTextNode(part));
    });
    const lastNode = fragment.lastChild;
    range.insertNode(fragment);
    if (lastNode) {
        range.setStartAfter(lastNode);
        range.collapse(true);
        selection.removeAllRanges();
        selection.addRange(range);
    }
};

const CanvasMarkdownPreview = ({ content, onChange, onBlur }: CanvasMarkdownPreviewProps) => {
    const { t } = useTranslation();
    const previewRef = useRef<HTMLDivElement | null>(null);
    const formatLabels = useMemo(() => ({
        codeBlock: {
            codeSnippet: t('codeBlock.codeSnippet'),
            diagram: t('codeBlock.diagram'),
            preview: t('codeBlock.preview'),
            code: t('codeBlock.code'),
            download: t('codeBlock.download'),
            copy: t('codeBlock.copy'),
            expand: t('codeBlock.expand'),
            collapse: t('codeBlock.collapse'),
            tableCopy: t('codeBlock.tableCopy'),
        },
        diagrams: {
            chartjsLoading: t('codeBlock.loading.chartjs'),
            d3Loading: t('codeBlock.loading.d3'),
            nomnomlLoading: t('codeBlock.loading.nomnoml'),
            mermaidLoading: t('codeBlock.loading.mermaid'),
            svgLoading: t('codeBlock.loading.svg'),
        },
        widgets: {
            creating: t('widgets.creating'),
        },
    }), [t]);
    const renderedContent = useMemo(
        () => formatText(content, { labels: formatLabels }),
        [content, formatLabels]
    );

    useLayoutEffect(() => {
        const root = previewRef.current;
        if (!root || !renderedContent) return;

        const updateCodeBlocks = () => {
            highlightCode(root);
            refreshCodeLineNumbers(root);
            root.querySelectorAll<HTMLElement>([
                '.code-block-header',
                '.diagram-preview',
                '.katex',
                '.table-copy-btn',
                'img',
            ].join(',')).forEach((element) => {
                element.contentEditable = 'false';
            });
        };
        updateCodeBlocks();
        const frame = window.requestAnimationFrame(updateCodeBlocks);

        return () => window.cancelAnimationFrame(frame);
    }, [renderedContent]);

    const emitSource = useCallback((root: HTMLDivElement) => {
        const source = renderedMarkdownToSource(root);
        onChange(source);
        return source;
    }, [onChange]);

    const handleInput = useCallback((event: FormEvent<HTMLDivElement>) => {
        emitSource(event.currentTarget);
    }, [emitSource]);

    const handleBlur = useCallback((event: ReactFocusEvent<HTMLDivElement>) => {
        if (
            event.relatedTarget instanceof Node
            && event.currentTarget.contains(event.relatedTarget)
        ) {
            return;
        }
        onBlur(renderedMarkdownToSource(event.currentTarget));
    }, [onBlur]);

    const handlePaste = useCallback((event: ReactClipboardEvent<HTMLDivElement>) => {
        event.preventDefault();
        insertPlainTextAtSelection(event.clipboardData.getData('text/plain'));
        emitSource(event.currentTarget);
    }, [emitSource]);

    const handleDrop = useCallback((event: ReactDragEvent<HTMLDivElement>) => {
        event.preventDefault();
        event.currentTarget.focus();
        insertPlainTextAtSelection(event.dataTransfer.getData('text/plain'));
        emitSource(event.currentTarget);
    }, [emitSource]);

    useEffect(() => {
        const root = previewRef.current;
        if (!root || !renderedContent) return;
        let cancelled = false;

        const renderVisuals = async () => {
            Utils.renderSvgPreviews?.(root);
            await Utils.renderCharts?.(root);
            if (cancelled) return;
            await Utils.renderD3?.(root);
            if (cancelled) return;
            await Utils.renderNomnoml?.(root);
            if (cancelled) return;
            await Utils.renderMermaid?.(root);
            if (cancelled) return;
            Utils.attachDiagramPan?.(root);
        };

        void renderVisuals();
        return () => {
            cancelled = true;
        };
    }, [renderedContent]);

    const showTemporaryButtonState = useCallback((
        button: HTMLButtonElement,
        label: string,
        restoreLabel: string,
        state: 'success' | 'error'
    ) => {
        const originalHtml = button.innerHTML;
        button.textContent = label;
        button.setAttribute('aria-label', label);
        button.classList.toggle('is-copy-success', state === 'success');
        button.classList.toggle('is-copy-error', state === 'error');
        window.setTimeout(() => {
            button.innerHTML = originalHtml;
            button.setAttribute('aria-label', restoreLabel);
            button.classList.remove('is-copy-success', 'is-copy-error');
        }, 1600);
    }, []);

    const handlePreviewClick = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
        const eventTarget = event.target instanceof Element ? event.target : null;
        const button = eventTarget?.closest('button');
        if (!(button instanceof HTMLButtonElement)) return;

        if (button.classList.contains('table-copy-btn')) {
            event.preventDefault();
            const table = button.closest('.table-wrapper')?.querySelector('table');
            if (!table) return;
            const copyLabel = t('codeBlock.tableCopy');
            navigator.clipboard?.writeText(table.textContent || '')
                .then(() => showTemporaryButtonState(
                    button,
                    t('codeBlock.tableCopied'),
                    copyLabel,
                    'success'
                ))
                .catch(() => showTemporaryButtonState(
                    button,
                    t('codeBlock.copyFailed'),
                    copyLabel,
                    'error'
                ));
            return;
        }

        const codeBlock = button.closest<HTMLElement>('.code-block');
        const codeElement = codeBlock?.querySelector('code');
        if (!codeBlock || !codeElement) return;
        const codeText = codeElement.textContent || '';

        if (button.classList.contains('code-tab-btn')) {
            const selectedTab = button.dataset.tab;
            if (!selectedTab) return;
            codeBlock.querySelectorAll<HTMLButtonElement>('.code-tab-btn').forEach((tab) => {
                const isSelected = tab === button;
                tab.classList.toggle('active', isSelected);
                tab.setAttribute('aria-selected', String(isSelected));
                tab.tabIndex = isSelected ? 0 : -1;
            });
            codeBlock.querySelectorAll<HTMLElement>('.code-block-pane').forEach((pane) => {
                const isSelected = pane.dataset.pane === selectedTab;
                pane.classList.toggle('active', isSelected);
                pane.toggleAttribute('hidden', !isSelected);
            });
            if (selectedTab === 'code') {
                window.requestAnimationFrame(() => refreshCodeLineNumbers(codeBlock));
            }
            return;
        }

        if (button.classList.contains('copy-code-btn')) {
            Utils.copyToClipboard(codeText, button);
            return;
        }

        if (button.classList.contains('download-code-btn')) {
            const filename = codeBlock.dataset.filename || 'code.txt';
            const language = codeBlock.dataset.language || 'plaintext';
            const extension = language === 'plaintext' ? 'txt' : language;
            const downloadName = filename.toLowerCase().endsWith(`.${extension}`)
                ? filename
                : `${filename}.${extension}`;
            Utils.downloadFile(codeText, downloadName, `text/${language}`);
            return;
        }

        if (button.classList.contains('toggle-code-btn')) {
            const codeContent = codeBlock.querySelector<HTMLElement>('.code-block-content');
            if (!codeContent) return;
            const willExpand = !codeContent.classList.contains('expanded');
            const label = willExpand ? t('codeBlock.collapse') : t('codeBlock.expand');
            codeContent.classList.toggle('expanded', willExpand);
            codeContent.classList.toggle('has-overflow', !willExpand);
            button.classList.toggle('expanded', willExpand);
            button.setAttribute('aria-expanded', String(willExpand));
            button.setAttribute('aria-label', label);
            button.title = label;
            codeContent.style.maxHeight = willExpand
                ? `${codeContent.scrollHeight}px`
                : (codeContent.dataset.initialMaxHeight || '200px');
            button.querySelector<HTMLElement>('.icon-expand')?.style.setProperty(
                'display',
                willExpand ? 'none' : 'block'
            );
            button.querySelector<HTMLElement>('.icon-collapse')?.style.setProperty(
                'display',
                willExpand ? 'block' : 'none'
            );
            window.requestAnimationFrame(() => refreshCodeLineNumbers(codeBlock));
        }
    }, [showTemporaryButtonState, t]);

    return (
        <div
            ref={previewRef}
            className="message-text ui-message-text chat-canvas-markdown"
            role="textbox"
            aria-label={t('canvas.editorLabel')}
            aria-multiline="true"
            contentEditable
            suppressContentEditableWarning
            spellCheck
            data-placeholder={t('canvas.empty')}
            onInput={handleInput}
            onBlur={handleBlur}
            onPaste={handlePaste}
            onDrop={handleDrop}
            onClick={handlePreviewClick}
            dangerouslySetInnerHTML={{ __html: renderedContent }}
        />
    );
};

export default memo(CanvasMarkdownPreview);
