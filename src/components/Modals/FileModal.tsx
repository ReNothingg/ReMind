import React, { useEffect, useState, useRef } from 'react';
import { fileService } from '../../services/fileService';
import { Utils } from '../../utils/utils';
import { DOMSafeUtils } from '../../utils/dom-safe';

const FileModal = ({ isOpen, onClose, file, content }) => {
    const modalRef = useRef(null);
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

        const handleClickOutside = (e) => {
            if (modalRef.current && !modalRef.current.contains(e.target)) {
                onClose();
            }
        };

        document.addEventListener('keydown', handleEscape);
        document.addEventListener('click', handleClickOutside);

        return () => {
            document.removeEventListener('keydown', handleEscape);
            document.removeEventListener('click', handleClickOutside);
        };
    }, [isOpen, onClose]);

    useEffect(() => {
        if (isOpen) {
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = '';
        }
    }, [isOpen]);

    if (!isOpen || !file) return null;

    const ext = file.name.split('.').pop()?.toLowerCase() || 'plaintext';
    const isImage = fileService.isImageFile(file) && content?.startsWith('data:image');
    const is3DModel = fileService.is3DModelFile(file) && content?.startsWith('data:');
    const isText = fileService.isTextFile(file);
    const isHtml = ext === 'html';

    return (
        <div className="file-modal active" ref={modalRef}>
            <div className="file-modal-content">
                <button className="file-modal-close" onClick={onClose} title="Закрыть (Esc)">
                    ×
                </button>

                <div className="file-modal-info-header">
                    <span className="file-name-display" title={file.name}>
                        {Utils.escapeHtml(file.name)}
                    </span>
                    <span className="file-size-display">
                        {fileService.formatFileSize(file.size)}
                    </span>
                    {isText && lineCount > 0 && (
                        <>
                            <span className="info-separator"> | </span>
                            <span className="line-count-data">{lineCount} строк</span>
                        </>
                    )}
                </div>

                {isImage && (
                    <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'auto', padding: '10px' }}>
                        <img
                            src={content}
                            alt={`Предпросмотр файла ${file.name}`}
                            style={{ display: 'block', maxWidth: '100%', maxHeight: 'calc(100% - 45px)', objectFit: 'contain', margin: 'auto' }}
                        />
                    </div>
                )}

                {is3DModel && (
                    <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'auto', padding: '10px' }}>
                        <model-viewer
                            src={content}
                            alt={`3D модель ${file.name}`}
                            camera-controls=""
                            auto-rotate=""
                            shadow-intensity="1"
                            environment-image="https://modelviewer.dev/shared-assets/environments/spruit_sunrise_1k_HDR.hdr"
                            exposure="1"
                            style={{ display: 'block', width: '100%', height: 'calc(100% - 45px)', backgroundColor: '#f0f0f0' }}
                        />
                    </div>
                )}

                {isHtml && (
                    <>
                        <div className="preview-tabs">
                            <button
                                className={`tab ${activeTab === 'preview' ? 'active' : ''}`}
                                data-tab="preview"
                                onClick={() => setActiveTab('preview')}
                            >
                                Предпросмотр
                            </button>
                            <button
                                className={`tab ${activeTab === 'code' ? 'active' : ''}`}
                                data-tab="code"
                                onClick={() => setActiveTab('code')}
                            >
                                Код ({lineCount} строк)
                            </button>
                        </div>
                        <div className="tab-content-wrapper">
                            <div className={`preview-tab tab-pane ${activeTab === 'preview' ? 'active' : ''}`} data-pane="preview">
                                <iframe
                                    srcDoc={content}
                                    sandbox="allow-forms"
                                    style={{ width: '100%', height: '100%', border: 'none' }}
                                />
                            </div>
                            <div className={`code-tab tab-pane ${activeTab === 'code' ? 'active' : ''}`} data-pane="code">
                                <pre className="line-numbers">
                                    <code className="language-html">{content}</code>
                                </pre>
                            </div>
                        </div>
                    </>
                )}

                {isText && !isHtml && (
                    <div className="code-tab tab-pane active single-code-view">
                        <pre className={`line-numbers language-${ext}`}>
                            <code className={`language-${ext}`}>{content}</code>
                        </pre>
                    </div>
                )}

                {!isImage && !is3DModel && !isText && (
                    <p style={{ padding: '20px', textAlign: 'center' }}>
                        Предпросмотр для файла "{Utils.escapeHtml(file.name)}" не поддерживается.
                    </p>
                )}
            </div>
        </div>
    );
};

export default FileModal;
