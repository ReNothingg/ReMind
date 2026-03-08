import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fileService } from '../../services/fileService';
import { cn } from '../../utils/cn';

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
        <div className="file-card group relative flex h-[92px] w-[92px] shrink-0 flex-col overflow-hidden rounded-[18px] border border-[rgba(var(--color-white-raw),0.12)] bg-[rgba(var(--color-black-raw),0.25)]">
            <div
                className={cn(
                    previewClass,
                    'file-card-preview mx-1.5 mt-1.5 flex flex-1 items-center justify-center overflow-hidden rounded-[14px] border border-[rgba(var(--color-white-raw),0.08)] bg-[rgba(var(--color-black-raw),0.2)]',
                    isText && 'is-text items-start p-1.5 font-mono text-[0.6rem] leading-[1.35] text-muted',
                    is3dModel && 'is-3d-model'
                )}
                onClick={handleClick}
                style={{ cursor: onPreview ? 'pointer' : 'default' }}
            >
                {isImage && preview ? (
                    <img src={preview} alt={file.name} className="image-thumbnail" />
                ) : is3dModel ? (
                    <div className="is-3d-model text-center text-[0.68rem] font-medium text-muted">{t('files.model3d')}</div>
                ) : isText && preview ? (
                    <pre className="max-h-[60px] overflow-hidden whitespace-pre-wrap break-all [mask-image:linear-gradient(to_bottom,black_60%,transparent_100%)]">
                        {preview.substring(5)}
                    </pre>
                ) : (
                    <img
                        src={fileService.getFileIconPath(file.name.split('.').pop()?.toLowerCase())}
                        alt={file.name}
                        className="generic-icon size-8 opacity-70"
                        onError={(e) => e.target.src = 'https://cdn.jsdelivr.net/gh/vscode-icons/vscode-icons/icons/default_file.svg'}
                    />
                )}
            </div>
            <div className="file-card-footer flex h-7 items-center gap-1.5 border-t border-[rgba(var(--color-white-raw),0.08)] bg-[rgba(var(--color-black-raw),0.2)] px-2 py-[5px]">
                <img
                    src={fileService.getFileIconPath(file.name.split('.').pop()?.toLowerCase())}
                    alt="icon"
                    className="file-card-footer-icon size-3.5 shrink-0 opacity-85"
                    onError={(e) => e.target.src = 'https://cdn.jsdelivr.net/gh/vscode-icons/vscode-icons/icons/default_file.svg'}
                />
                <div className="file-card-footer-info min-w-0">
                    <span className="file-card-name block max-w-[55px] truncate text-[0.68rem] leading-[1.2] font-semibold tracking-[0.01em] text-foreground">
                        {fileService.escapeHtml(file.name)}
                    </span>
                    <span className="file-card-size block text-[0.55rem] text-subtle">
                        {fileService.formatFileSize(file.size)}
                    </span>
                </div>
                <button
                    className="file-card-remove-btn absolute top-1 right-1 z-[1] flex size-6 items-center justify-center rounded-full border border-[rgba(var(--color-white-raw),0.2)] bg-[rgba(var(--color-black-raw),0.65)] text-base font-bold leading-none text-white opacity-0 transition duration-200 hover:bg-[rgba(var(--color-accent-raw),0.9)] group-hover:opacity-100"
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
