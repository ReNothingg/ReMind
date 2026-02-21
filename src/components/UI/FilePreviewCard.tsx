import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fileService } from '../../services/fileService';

const FilePreviewCard = ({ file, onRemove, onPreview }) => {
    const { t } = useTranslation();
    const [preview, setPreview] = useState(null);
    const [fileContent, setFileContent] = useState(null);

    useEffect(() => {
        if (fileService.isImageFile(file)) {
            const reader = new FileReader();
            reader.onload = (e) => {
                setPreview(e.target.result);
                setFileContent(e.target.result);
            };
            reader.readAsDataURL(file);
        } else if (fileService.is3DModelFile(file)) {
            setPreview('3d-model');
            const reader = new FileReader();
            reader.onload = (e) => setFileContent(e.target.result);
            reader.readAsDataURL(file);
        } else if (fileService.isTextFile(file)) {
            const reader = new FileReader();
            reader.onload = (e) => {
                const text = e.target.result || '';
                setPreview(`text:${text.substring(0, 200)}`);
                setFileContent(text);
            };
            reader.readAsText(file);
        }
    }, [file]);

    const handleClick = () => {
        if (onPreview && fileContent) {
            onPreview(file, fileContent);
        }
    };

    const isImage = fileService.isImageFile(file);
    const is3dModel = fileService.is3DModelFile(file);
    const isText = fileService.isTextFile(file);
    const previewClass = [
        'file-card-preview',
        isText ? 'is-text' : '',
        is3dModel ? 'is-3d-model' : ''
    ].filter(Boolean).join(' ');

    return (
        <div className="file-card">
            <div className={previewClass} onClick={handleClick} style={{ cursor: onPreview ? 'pointer' : 'default' }}>
                {isImage && preview ? (
                    <img src={preview} alt={file.name} className="image-thumbnail" />
                ) : is3dModel ? (
                    <div className="is-3d-model">{t('files.model3d')}</div>
                ) : isText && preview ? (
                    <pre>{preview.substring(5)}</pre>
                ) : (
                    <img
                        src={fileService.getFileIconPath(file.name.split('.').pop()?.toLowerCase())}
                        alt={file.name}
                        className="generic-icon"
                        onError={(e) => e.target.src = 'https://cdn.jsdelivr.net/gh/vscode-icons/vscode-icons/icons/default_file.svg'}
                    />
                )}
            </div>
            <div className="file-card-footer">
                <img
                    src={fileService.getFileIconPath(file.name.split('.').pop()?.toLowerCase())}
                    alt="icon"
                    className="file-card-footer-icon"
                    onError={(e) => e.target.src = 'https://cdn.jsdelivr.net/gh/vscode-icons/vscode-icons/icons/default_file.svg'}
                />
                <div className="file-card-footer-info">
                    <span className="file-card-name">{fileService.escapeHtml(file.name)}</span>
                    <span className="file-card-size">{fileService.formatFileSize(file.size)}</span>
                </div>
                <button
                    className="file-card-remove-btn"
                    onClick={() => onRemove()}
                    title={t('files.removeFile')}
                    aria-label={t('files.removeFile')}
                >
                    x
                </button>
            </div>
        </div>
    );
};

export default FilePreviewCard;
