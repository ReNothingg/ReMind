import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { apiService, type ChatStreamResult } from '../../services/api';
import { Utils } from '../../utils/utils';
import ModalShell from '../UI/ModalShell';
import CustomSelect from '../UI/CustomSelect';
import { cn } from '../../utils/cn';

type ImageLightboxProps = {
    isOpen: boolean;
    imageSrc?: string | null;
    messageElement?: HTMLElement | null;
    onClose: () => void;
    currentModel?: string | null;
    sessionId?: string | null;
};

const getSourceUserMessageElement = (messageElement?: HTMLElement | null): HTMLElement | null => {
    if (!messageElement) {
        return null;
    }

    let userMessageElement: Element | null = messageElement.previousElementSibling;

    while (userMessageElement && !userMessageElement.classList.contains('user-message')) {
        userMessageElement = userMessageElement.previousElementSibling;
    }

    return userMessageElement instanceof HTMLElement ? userMessageElement : null;
};

const getSourcePrompt = (messageElement?: HTMLElement | null) => {
    const userMessageElement = getSourceUserMessageElement(messageElement);
    return (
        userMessageElement?.dataset?.rawContent ||
        userMessageElement?.textContent ||
        ''
    ).trim();
};

const normalizeModelName = (modelName?: string | null) => {
    if (!modelName) {
        return '';
    }

    return modelName
        .replace(/[_-]+/g, ' ')
        .replace(/\b\w/g, (char) => char.toUpperCase());
};

const ImageLightbox = ({ isOpen, imageSrc, messageElement, onClose, currentModel, sessionId }: ImageLightboxProps) => {
    const [isLoading, setIsLoading] = useState(false);
    const [hasImageError, setHasImageError] = useState(false);
    const [currentImageSrc, setCurrentImageSrc] = useState(imageSrc);
    const [imageStyle, setImageStyle] = useState('realistic');
    const [imageMeta, setImageMeta] = useState<{ width: number; height: number } | null>(null);
    const imageRef = useRef<HTMLImageElement | null>(null);
    const { t } = useTranslation();

    useEffect(() => {
        if (isOpen && imageSrc) {
            setCurrentImageSrc(imageSrc);
            setHasImageError(false);
            setImageMeta(null);
        }
    }, [isOpen, imageSrc]);

    useEffect(() => {
        document.body.style.overflow = isOpen ? 'hidden' : '';

        return () => {
            document.body.style.overflow = '';
        };
    }, [isOpen]);

    useEffect(() => {
        const handleEscape = (event) => {
            if (event.key === 'Escape' && isOpen) {
                onClose();
            }
        };

        document.addEventListener('keydown', handleEscape);
        return () => document.removeEventListener('keydown', handleEscape);
    }, [isOpen, onClose]);

    const translate = (key: string, defaultValue: string, options: Record<string, unknown> = {}) => t(key, { defaultValue, ...options });
    const sourcePrompt = getSourcePrompt(messageElement);
    const styleOptions = [
        { value: 'realistic', label: translate('imageLightbox.styles.realistic', 'Realistic') },
        { value: 'cartoon', label: translate('imageLightbox.styles.cartoon', 'Cartoon') },
        { value: 'anime', label: translate('imageLightbox.styles.anime', 'Anime') },
        { value: 'oil_painting', label: translate('imageLightbox.styles.oilPainting', 'Oil painting') },
        { value: 'watercolor', label: translate('imageLightbox.styles.watercolor', 'Watercolor') },
        { value: 'pencil_sketch', label: translate('imageLightbox.styles.pencilSketch', 'Pencil sketch') },
    ];
    const activeStyleLabel =
        styleOptions.find((option) => option.value === imageStyle)?.label || imageStyle;
    const modelLabel =
        currentModel === 'demo_image'
            ? 'Mind image'
            : normalizeModelName(currentModel);

    const handleRegenerate = async () => {
        if (isLoading) {
            return;
        }

        if (!getSourceUserMessageElement(messageElement)) {
            Utils.showPopupWarning?.(
                translate(
                    'imageLightbox.errors.missingSourceMessage',
                    'Could not find the original user message.'
                )
            );
            return;
        }

        if (!sourcePrompt) {
            Utils.showPopupWarning?.(
                translate(
                    'imageLightbox.errors.missingPrompt',
                    'No source prompt was found for image regeneration.'
                )
            );
            return;
        }

        setIsLoading(true);

        try {
            const formData = new FormData();
            formData.append('message', sourcePrompt);
            formData.append('model', currentModel || 'demo_image');
            formData.append('image_style', imageStyle);
            formData.append('regenerate_image_only', 'true');
            formData.append('session_id', sessionId || '');

            const result = await new Promise<ChatStreamResult>((resolve, reject) => {
                apiService.chat(formData, undefined, {
                    onComplete: resolve,
                    onError: reject,
                }).catch(reject);
            });

            let imagePath = null;
            if (Array.isArray(result?.images)) {
                imagePath = result.images[0] || null;
            } else if (typeof result?.images === 'string') {
                imagePath = result.images;
            }

            if (!imagePath) {
                throw new Error(
                    translate(
                        'imageLightbox.errors.missingResult',
                        'The model did not return a new image.'
                    )
                );
            }

            const fullUrl = imagePath.startsWith('http')
                ? imagePath
                : `${apiService.baseURL}${imagePath}`;
            const previousSrc = currentImageSrc;

            setCurrentImageSrc(fullUrl);
            setHasImageError(false);
            setImageMeta(null);

            messageElement?.querySelectorAll('.attached-img').forEach((imgEl) => {
                if (imgEl instanceof HTMLImageElement && (!previousSrc || imgEl.src === previousSrc)) {
                    imgEl.src = fullUrl;
                }
            });
        } catch (error) {
            console.error('Failed to regenerate image:', error);
            const errorMessage = error instanceof Error ? error.message : 'Unknown error';

            Utils.showPopupWarning?.(
                translate(
                    'imageLightbox.errors.regenerateFailed',
                    'Could not regenerate the image: {{message}}',
                    { message: errorMessage }
                )
            );
        } finally {
            setIsLoading(false);
        }
    };

    const handleDownload = async () => {
        if (!currentImageSrc) {
            Utils.showPopupWarning?.(
                translate(
                    'imageLightbox.errors.missingImage',
                    'No image is available for download.'
                )
            );
            return;
        }

        try {
            const response = await fetch(currentImageSrc);
            if (!response.ok) {
                throw new Error(response.statusText);
            }

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');

            a.style.display = 'none';
            a.href = url;

            let ext = 'jpg';
            try {
                if (blob.type && blob.type.includes('/')) {
                    ext = blob.type.split('/').pop() || ext;
                } else {
                    const parsed = new URL(currentImageSrc);
                    const pathExt = (parsed.pathname.split('.').pop() || '').toLowerCase();
                    if (pathExt) {
                        ext = pathExt;
                    }
                }
            } catch {
            }

            a.download = `remind-art-${Date.now()}.${ext}`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            a.remove();
        } catch (error) {
            console.error('Failed to download image:', error);

            Utils.showPopupWarning?.(
                translate(
                    'imageLightbox.errors.downloadFailed',
                    'Could not download the image. The original file will be opened in a new tab.'
                )
            );
            window.open(currentImageSrc, '_blank');
        }
    };

    const handleImageLoad = () => {
        setHasImageError(false);

        if (!imageRef.current) {
            setImageMeta(null);
            return;
        }

        setImageMeta({
            width: imageRef.current.naturalWidth,
            height: imageRef.current.naturalHeight,
        });
    };

    const handleImageError = () => {
        setHasImageError(true);
        setImageMeta(null);
    };

    if (!isOpen) {
        return null;
    }

    return (
        <ModalShell
            ariaLabel={translate(
                currentModel === 'demo_image'
                    ? 'imageLightbox.demoTitle'
                    : 'imageLightbox.title',
                currentModel === 'demo_image' ? 'ReMind demo image' : 'Image preview'
            )}
            className="image-lightbox active px-3 py-4 sm:px-4 sm:py-6"
            contentClassName="w-full max-w-[min(900px,calc(100vw-32px))] overflow-visible border-transparent bg-transparent shadow-none"
            onBackdropClick={onClose}
            onRequestClose={onClose}
        >
            <section
                className="image-lightbox-panel"
            >
                <div className="image-lightbox-header">
                    <div className="image-lightbox-heading">
                        <span className="ui-badge image-lightbox-badge">
                            {translate('imageLightbox.badge', 'Preview')}
                        </span>
                        <div className="image-lightbox-copy">
                            <h2 className="image-lightbox-title">
                                {translate(
                                    currentModel === 'demo_image'
                                        ? 'imageLightbox.demoTitle'
                                        : 'imageLightbox.title',
                                    currentModel === 'demo_image'
                                        ? 'ReMind demo image'
                                        : 'Image preview'
                                )}
                            </h2>
                        </div>
                    </div>

                    <div className="image-lightbox-header-actions">
                        <div className="image-lightbox-meta-cluster">
                            {modelLabel && (
                                <span className="ui-badge image-lightbox-meta-badge">
                                    {modelLabel}
                                </span>
                            )}
                            {imageMeta && (
                                <span className="ui-badge image-lightbox-meta-badge">
                                    {translate(
                                        'imageLightbox.details.resolution',
                                        '{{width}} x {{height}} px',
                                        imageMeta
                                    )}
                                </span>
                            )}
                        </div>

                        <button
                            className="lightbox-close-btn ui-icon-control rounded-xl border-transparent bg-transparent text-muted hover:bg-interactive hover:text-foreground"
                            onClick={onClose}
                            aria-label={translate('imageLightbox.close', 'Close')}
                            type="button"
                        >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <line x1="18" y1="6" x2="6" y2="18" />
                                <line x1="6" y1="6" x2="18" y2="18" />
                            </svg>
                        </button>
                    </div>
                </div>

                <div className="lightbox-image-wrapper image-lightbox-stage">
                    <div className="image-lightbox-stage-inner">
                        <img
                            ref={imageRef}
                            id="lightboxImage"
                            className={cn(
                                'lightbox-image',
                                hasImageError && 'opacity-0'
                            )}
                            src={currentImageSrc}
                            alt={translate('imageLightbox.previewAlt', 'Image preview')}
                            onLoad={handleImageLoad}
                            onError={handleImageError}
                        />

                        {hasImageError && (
                            <div className="image-lightbox-empty-state">
                                <div className="image-lightbox-empty-card">
                                    <div className="image-lightbox-empty-title">
                                        {translate(
                                            'imageLightbox.errors.previewTitle',
                                            'Image preview unavailable'
                                        )}
                                    </div>
                                    <div className="image-lightbox-empty-description">
                                        {translate(
                                            'imageLightbox.errors.previewDescription',
                                            'Check the file path or regenerate the image.'
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}

                        <div
                            className={cn('lightbox-loader', isLoading && 'visible')}
                            aria-hidden={!isLoading}
                        >
                            <div className="spinner size-10 animate-spin rounded-full border-2 border-white/25 border-t-white" />
                        </div>
                    </div>
                </div>

                <div className="image-lightbox-footer">
                    <div className="image-lightbox-context-card">
                        <div className="image-lightbox-context-label">
                            {translate('imageLightbox.promptLabel', 'Original prompt')}
                        </div>
                        <div className="image-lightbox-context-text">
                            {sourcePrompt ||
                                translate(
                                    'imageLightbox.promptFallback',
                                    'The original prompt is unavailable for this image.'
                                )}
                        </div>
                        <div className="image-lightbox-context-meta">
                            <span className="ui-badge image-lightbox-context-badge">
                                {translate(
                                    'imageLightbox.details.style',
                                    'Style: {{style}}',
                                    { style: activeStyleLabel }
                                )}
                            </span>
                            {imageMeta && (
                                <span className="ui-badge image-lightbox-context-badge">
                                    {translate(
                                        'imageLightbox.details.resolution',
                                        '{{width}} x {{height}} px',
                                        imageMeta
                                    )}
                                </span>
                            )}
                        </div>
                    </div>

                    <div className="lightbox-controls image-lightbox-controls">
                        <CustomSelect
                            className="image-lightbox-style-select"
                            label={translate('imageLightbox.styleLabel', 'Style')}
                            value={imageStyle}
                            onChange={setImageStyle}
                            options={styleOptions}
                            disabled={isLoading}
                        />

                        <div className="image-lightbox-actions">
                            <button
                                id="lightboxRegenerateBtn"
                                className="lightbox-btn ui-button-secondary image-lightbox-action-button"
                                onClick={handleRegenerate}
                                disabled={isLoading}
                                title={translate('imageLightbox.actions.regenerate', 'Regenerate')}
                                type="button"
                            >
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
                                    <path d="M21 3v5h-5" />
                                    <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
                                    <path d="M3 21v-5h5" />
                                </svg>
                                <span>
                                    {isLoading
                                        ? translate('imageLightbox.actions.regenerating', 'Generating...')
                                        : translate('imageLightbox.actions.regenerate', 'Regenerate')}
                                </span>
                            </button>

                            <button
                                id="lightboxDownloadBtn"
                                className="lightbox-btn ui-button-secondary image-lightbox-action-button"
                                onClick={handleDownload}
                                disabled={isLoading || !currentImageSrc}
                                title={translate('imageLightbox.actions.download', 'Download')}
                                type="button"
                            >
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                    <polyline points="7 10 12 15 17 10" />
                                    <line x1="12" x2="12" y1="15" y2="3" />
                                </svg>
                                <span>{translate('imageLightbox.actions.download', 'Download')}</span>
                            </button>
                        </div>
                    </div>
                </div>
            </section>
        </ModalShell>
    );
};

export default ImageLightbox;
