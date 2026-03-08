import React, { useEffect, useState } from 'react';
import { fileService } from '../../services/fileService';
import { Utils } from '../../utils/utils';
import ModalShell from '../UI/ModalShell';
import { cn } from '../../utils/cn';

const FileModal = ({ isOpen, onClose, file, content }) => {
    const [activeTab, setActiveTab] = useState('preview');
    const [lineCount, setLineCount] = useState(0);

    useEffect(() => {
        if (!isOpen || !content) return;

        if (fileService.isTextFile(file)) {
            const count = (content.match(/\n/g) || []).length + 1;
            setLineCount(count);
        }
    }, [isOpen, content, file]);

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

    if (!isOpen || !file) return null;

    const ext = file.name.split('.').pop()?.toLowerCase() || 'plaintext';
    const isImage = fileService.isImageFile(file) && content?.startsWith('data:image');
    const is3DModel = fileService.is3DModelFile(file) && content?.startsWith('data:');
    const isText = fileService.isTextFile(file);
    const isHtml = ext === 'html';

    return (
        <ModalShell
            className="file-modal active px-3 py-4 sm:px-4 sm:py-6"
            contentClassName="file-modal-content flex h-[min(90vh,820px)] w-full max-w-5xl flex-col rounded-[18px] border-border bg-surface text-foreground shadow-[var(--shadow-xl)]"
            onBackdropClick={onClose}
        >
            <button
                className="file-modal-close ui-icon-control absolute right-4 top-4 z-10 size-10 rounded-xl border-transparent bg-interactive text-muted hover:bg-surface-alt hover:text-foreground"
                onClick={onClose}
                title="Р—Р°РєСЂС‹С‚СЊ (Esc)"
                type="button"
            >
                Г—
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
                        <span className="line-count-data text-sm text-muted">{lineCount} СЃС‚СЂРѕРє</span>
                    </>
                )}
            </div>

            {isImage && (
                <div className="flex flex-1 items-center justify-center overflow-auto p-4">
                    <img
                        src={content}
                        alt={`РџСЂРµРґРїСЂРѕСЃРјРѕС‚СЂ С„Р°Р№Р»Р° ${file.name}`}
                        className="block max-h-full max-w-full rounded-xl object-contain"
                    />
                </div>
            )}

            {is3DModel && (
                <div className="flex flex-1 items-center justify-center overflow-auto p-4">
                    <model-viewer
                        src={content}
                        alt={`3D РјРѕРґРµР»СЊ ${file.name}`}
                        camera-controls=""
                        auto-rotate=""
                        shadow-intensity="1"
                        environment-image="https://modelviewer.dev/shared-assets/environments/spruit_sunrise_1k_HDR.hdr"
                        exposure="1"
                        style={{ display: 'block', width: '100%', height: '100%', backgroundColor: '#f0f0f0', borderRadius: '16px' }}
                    />
                </div>
            )}

            {isHtml && (
                <>
                    <div className="preview-tabs flex items-center gap-2 border-b border-border px-4 py-3 sm:px-5">
                        <button
                            className={cn(
                                'tab rounded-xl px-4 py-2 text-sm font-medium transition duration-200 ease-out',
                                activeTab === 'preview'
                                    ? 'active bg-interactive text-foreground'
                                    : 'text-muted hover:bg-surface-alt hover:text-foreground'
                            )}
                            data-tab="preview"
                            onClick={() => setActiveTab('preview')}
                            type="button"
                        >
                            РџСЂРµРґРїСЂРѕСЃРјРѕС‚СЂ
                        </button>
                        <button
                            className={cn(
                                'tab rounded-xl px-4 py-2 text-sm font-medium transition duration-200 ease-out',
                                activeTab === 'code'
                                    ? 'active bg-interactive text-foreground'
                                    : 'text-muted hover:bg-surface-alt hover:text-foreground'
                            )}
                            data-tab="code"
                            onClick={() => setActiveTab('code')}
                            type="button"
                        >
                            РљРѕРґ ({lineCount} СЃС‚СЂРѕРє)
                        </button>
                    </div>

                    <div className="tab-content-wrapper min-h-0 flex-1">
                        <div className={cn('preview-tab tab-pane h-full', activeTab === 'preview' ? 'active block' : 'hidden')} data-pane="preview">
                            <iframe
                                srcDoc={content}
                                sandbox="allow-forms"
                                className="h-full w-full border-0"
                            />
                        </div>
                        <div className={cn('code-tab tab-pane h-full', activeTab === 'code' ? 'active block' : 'hidden')} data-pane="code">
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

            {!isImage && !is3DModel && !isText && (
                <p className="flex flex-1 items-center justify-center px-6 text-center text-sm text-muted">
                    РџСЂРµРґРїСЂРѕСЃРјРѕС‚СЂ РґР»СЏ С„Р°Р№Р»Р° "{Utils.escapeHtml(file.name)}" РЅРµ РїРѕРґРґРµСЂР¶РёРІР°РµС‚СЃСЏ.
                </p>
            )}
        </ModalShell>
    );
};

export default FileModal;
