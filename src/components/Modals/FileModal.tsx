import {
    useEffect,
    useId,
    useRef,
    useState,
    type KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import { fileService } from '../../services/fileService';
import { Utils } from '../../utils/utils';
import { highlightCode } from '../../utils/formatting';
import ModalShell from '../UI/ModalShell';
import { cn } from '../../utils/cn';

type FileTab = 'preview' | 'code';

const FileModal = ({ isOpen, onClose, file, content }) => {
    const { t } = useTranslation();
    const [activeTab, setActiveTab] = useState<FileTab>('preview');
    const contentRef = useRef<HTMLDivElement | null>(null);
    const tabGroupId = useId();

    const tabId = (tab: FileTab) => `${tabGroupId}-${tab}-tab`;
    const panelId = (tab: FileTab) => `${tabGroupId}-${tab}-panel`;

    const handleTabsKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
        const tabs = Array.from(
            event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')
        );
        const currentIndex = tabs.findIndex((tab) => tab === document.activeElement);
        if (currentIndex < 0) return;

        const isRtl = window.getComputedStyle(event.currentTarget).direction === 'rtl';
        let nextIndex = currentIndex;

        if (event.key === 'ArrowRight') {
            nextIndex = (currentIndex + (isRtl ? -1 : 1) + tabs.length) % tabs.length;
        } else if (event.key === 'ArrowLeft') {
            nextIndex = (currentIndex + (isRtl ? 1 : -1) + tabs.length) % tabs.length;
        } else if (event.key === 'Home') {
            nextIndex = 0;
        } else if (event.key === 'End') {
            nextIndex = tabs.length - 1;
        } else {
            return;
        }

        event.preventDefault();
        const nextTab = tabs[nextIndex];
        const nextValue = nextTab?.dataset.tab as FileTab | undefined;
        if (!nextTab || !nextValue) return;
        setActiveTab(nextValue);
        nextTab.focus();
    };

    useEffect(() => {
        if (!isOpen) return;

        const handleEscape = (e) => {
            if (e.key === 'Escape') {
                onClose();
            }
        };

        document.addEventListener('keydown', handleEscape);
        return () => {
            document.removeEventListener('keydown', handleEscape);
        };
    }, [isOpen, onClose]);

    useEffect(() => {
        if (isOpen) {
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = '';
        }

        return () => {
            document.body.style.overflow = '';
        };
    }, [isOpen]);

    useEffect(() => {
        if (!isOpen || !contentRef.current) return;

        const frame = window.requestAnimationFrame(() => {
            highlightCode(contentRef.current || undefined);

            const codeBlocks = contentRef.current?.querySelectorAll('pre.line-numbers') || [];
            codeBlocks.forEach((pre) => {
                if (window.Prism?.plugins?.lineNumbers) {
                    try {
                        window.Prism.plugins.lineNumbers.resize(pre);
                    } catch (error) {
                        console.warn('Failed to initialize line numbers in file modal:', error);
                    }
                }
            });
        });

        return () => window.cancelAnimationFrame(frame);
    }, [activeTab, content, isOpen]);

    if (!isOpen || !file) return null;

    const ext = file.name.split('.').pop()?.toLowerCase() || 'plaintext';
    const isImage = fileService.isImageFile(file) && content?.startsWith('data:image');
    const isText = fileService.isTextFile(file);
    const isHtml = ext === 'html';
    const lineCount = isText && content ? (content.match(/\n/g) || []).length + 1 : 0;

    return (
        <ModalShell
            ariaLabel={t('files.previewAlt', { name: file.name })}
            className="file-modal active px-3 py-4 sm:px-4 sm:py-6"
            contentClassName="file-modal-content flex h-[min(90vh,820px)] w-full max-w-5xl flex-col rounded-xl border-border bg-surface text-foreground"
            onBackdropClick={onClose}
            onRequestClose={onClose}
        >
            <button
                className="file-modal-close ui-icon-control absolute right-4 top-4 z-10 size-10 rounded-md border-transparent bg-interactive text-muted hover:bg-surface-alt hover:text-foreground"
                onClick={onClose}
                title={t('common.closeEsc')}
                aria-label={t('common.closeEsc')}
                type="button"
            >
                x
            </button>

            <div className="file-modal-info-header flex flex-wrap items-center gap-2 border-b border-border px-4 py-3 pr-16 text-sm sm:px-5">
                <span className="file-name-display min-w-0 flex-1 truncate font-semibold text-foreground" title={file.name}>
                    {Utils.escapeHtml(file.name)}
                </span>
                <span className="file-size-display ui-badge">
                    {fileService.formatFileSize(file.size)}
                </span>
                {isText && lineCount > 0 && (
                    <>
                        <span className="info-separator text-subtle">|</span>
                        <span className="line-count-data text-sm text-muted">
                            {t('files.lines', { count: lineCount })}
                        </span>
                    </>
                )}
            </div>

            <div ref={contentRef} className="flex min-h-0 flex-1 flex-col">
                {isImage && (
                    <div className="flex h-full items-center justify-center overflow-auto p-4">
                        <img
                            src={content}
                            alt={t('files.previewAlt', { name: file.name })}
                            className="block max-h-full max-w-full rounded-lg object-contain"
                        />
                    </div>
                )}

                {isHtml && (
                    <>
                        <div
                            className="preview-tabs flex items-center gap-2 border-b border-border px-4 py-3 sm:px-5"
                            role="tablist"
                            aria-label={t('files.preview')}
                            aria-orientation="horizontal"
                            onKeyDown={handleTabsKeyDown}
                        >
                            <button
                                className={cn(
                                    'tab rounded-md px-4 py-2 text-sm font-medium transition duration-200 ease-out',
                                    activeTab === 'preview'
                                        ? 'active bg-interactive text-foreground'
                                        : 'text-muted hover:bg-surface-alt hover:text-foreground'
                                )}
                                data-tab="preview"
                                onClick={() => setActiveTab('preview')}
                                type="button"
                                role="tab"
                                id={tabId('preview')}
                                aria-controls={panelId('preview')}
                                aria-selected={activeTab === 'preview'}
                                tabIndex={activeTab === 'preview' ? 0 : -1}
                            >
                                {t('files.preview')}
                            </button>
                            <button
                                className={cn(
                                    'tab rounded-md px-4 py-2 text-sm font-medium transition duration-200 ease-out',
                                    activeTab === 'code'
                                        ? 'active bg-interactive text-foreground'
                                        : 'text-muted hover:bg-surface-alt hover:text-foreground'
                                )}
                                data-tab="code"
                                onClick={() => setActiveTab('code')}
                                type="button"
                                role="tab"
                                id={tabId('code')}
                                aria-controls={panelId('code')}
                                aria-selected={activeTab === 'code'}
                                tabIndex={activeTab === 'code' ? 0 : -1}
                            >
                                {t('files.code')} ({t('files.lines', { count: lineCount })})
                            </button>
                        </div>

                        <div className="tab-content-wrapper min-h-0 flex-1">
                            <div
                                className={cn('preview-tab tab-pane h-full', activeTab === 'preview' ? 'active block' : 'hidden')}
                                data-pane="preview"
                                role="tabpanel"
                                id={panelId('preview')}
                                aria-labelledby={tabId('preview')}
                                hidden={activeTab !== 'preview'}
                            >
                                <iframe
                                    srcDoc={content}
                                    sandbox="allow-forms"
                                    className="h-full w-full border-0"
                                    title={t('files.previewAlt', { name: file.name })}
                                />
                            </div>
                            <div
                                className={cn('code-tab tab-pane h-full', activeTab === 'code' ? 'active block' : 'hidden')}
                                data-pane="code"
                                role="tabpanel"
                                id={panelId('code')}
                                aria-labelledby={tabId('code')}
                                hidden={activeTab !== 'code'}
                            >
                                <pre className="line-numbers ui-scrollbar-thin h-full overflow-auto p-4 sm:p-5">
                                    <code className="language-html">{content}</code>
                                </pre>
                            </div>
                        </div>
                    </>
                )}

                {isText && !isHtml && (
                    <div className="code-tab tab-pane active single-code-view min-h-0 flex-1">
                        <pre className={`line-numbers language-${ext} ui-scrollbar-thin h-full overflow-auto p-4 sm:p-5`}>
                            <code className={`language-${ext}`}>{content}</code>
                        </pre>
                    </div>
                )}

                {!isImage && !isText && (
                    <p className="flex flex-1 items-center justify-center px-6 text-center text-sm text-muted">
                        {t('files.previewUnavailable', { name: file.name })}
                    </p>
                )}
            </div>
        </ModalShell>
    );
};

export default FileModal;
