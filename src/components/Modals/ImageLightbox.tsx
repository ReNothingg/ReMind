import React, { useState, useEffect, useRef } from 'react';
import { apiService } from '../../services/api';
import { Utils } from '../../utils/utils';

const ImageLightbox = ({ isOpen, imageSrc, messageElement, onClose, currentModel, sessionId }) => {
    const [isLoading, setIsLoading] = useState(false);
    const [currentImageSrc, setCurrentImageSrc] = useState(imageSrc);
    const [imageStyle, setImageStyle] = useState('realistic');
    const lightboxRef = useRef(null);
    const imageRef = useRef(null);

    useEffect(() => {
        if (isOpen && imageSrc) {
            setCurrentImageSrc(imageSrc);
        }
    }, [isOpen, imageSrc]);

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
        const handleEscape = (e) => {
            if (e.key === 'Escape' && isOpen) {
                onClose();
            }
        };
        document.addEventListener('keydown', handleEscape);
        return () => document.removeEventListener('keydown', handleEscape);
    }, [isOpen, onClose]);

    const handleRegenerate = async () => {
        if (!messageElement || isLoading) return;
        let userMessageElement = messageElement.previousElementSibling;
        while (userMessageElement && !userMessageElement.classList.contains('user-message')) {
            userMessageElement = userMessageElement.previousElementSibling;
        }
        if (!userMessageElement) {
            Utils.showPopupWarning?.('Не найдено пользовательское сообщение для регенерации.');
            return;
        }

        const userMessageText = userMessageElement.dataset?.rawContent || userMessageElement.textContent || '';
        if (!userMessageText.trim()) {
            Utils.showPopupWarning?.('Нет текста для регенерации изображения.');
            return;
        }

        setIsLoading(true);

        try {
            const formData = new FormData();
            formData.append('message', userMessageText);
            formData.append('model', currentModel || 'mindart');
            formData.append('image_style', imageStyle);
            formData.append('regenerate_image_only', 'true');
            formData.append('user_id', sessionId || '');

            const response = await fetch(`${apiService.baseURL}/chat`, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.statusText}`);
            }

            const result = await response.json();

            let imagePath = null;
            if (Array.isArray(result?.images)) {
                imagePath = result.images[0] || null;
            } else if (typeof result?.images === 'string') {
                imagePath = result.images;
            }

            if (!imagePath) {
                throw new Error('Сервер не вернул новое изображение.');
            }

            const fullUrl = imagePath.startsWith('http') ? imagePath : `${apiService.baseURL}${imagePath}`;
            setCurrentImageSrc(fullUrl);
            const imgEl = messageElement.querySelector('.attached-img');
            if (imgEl) {
                imgEl.src = fullUrl;
            }
        } catch (error) {
            console.error('Failed to regenerate image:', error);
            Utils.showPopupWarning?.(`Не удалось регенерировать изображение: ${error.message}`);
        } finally {
            setIsLoading(false);
        }
    };

    const handleDownload = async () => {
        if (!currentImageSrc) {
            Utils.showPopupWarning?.('Нет изображения для скачивания.');
            return;
        }

        try {
            const response = await fetch(currentImageSrc);
            if (!response.ok) throw new Error(`Ошибка сети: ${response.statusText}`);
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            let ext = 'jpg';
            try {
                if (blob.type && blob.type.includes('/')) {
                    ext = blob.type.split('/').pop();
                } else {
                    const parsed = new URL(currentImageSrc);
                    const pathExt = (parsed.pathname.split('.').pop() || '').toLowerCase();
                    if (pathExt) ext = pathExt;
                }
            } catch (e) { }
            a.download = `remind-art-${Date.now()}.${ext}`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            a.remove();
        } catch (error) {
            console.error('Ошибка скачивания изображения:', error);
            Utils.showPopupWarning?.('Не удалось скачать изображение. Попробуйте сохранить его через контекстное меню (правый клик).');
            window.open(currentImageSrc, '_blank');
        }
    };

    if (!isOpen) return null;

    return (
        <div
            ref={lightboxRef}
            className="image-lightbox active"
            id="imageLightbox"
            onClick={(e) => {
                if (e.target === lightboxRef.current) {
                    onClose();
                }
            }}
        >
            <div className="lightbox-image-wrapper">
                <img
                    ref={imageRef}
                    id="lightboxImage"
                    className="lightbox-image"
                    src={currentImageSrc}
                    alt="Lightbox"
                />
                <div className={`lightbox-loader ${isLoading ? 'visible' : ''}`}>
                    <div className="spinner"></div>
                </div>
            </div>

            <button className="lightbox-close-btn" onClick={onClose} aria-label="Закрыть">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
            </button>

            <div className="lightbox-controls">
                <div className="lightbox-style-group">
                    <div className="lightbox-select-wrapper">
                        <select
                            id="lightboxStyleSelect"
                            value={imageStyle}
                            onChange={(e) => setImageStyle(e.target.value)}
                            disabled={isLoading}
                        >
                            <option value="realistic">Реалистичный</option>
                            <option value="cartoon">Мультяшный</option>
                            <option value="anime">Аниме</option>
                            <option value="oil_painting">Масляная живопись</option>
                            <option value="watercolor">Акварель</option>
                            <option value="pencil_sketch">Карандашный набросок</option>
                        </select>
                    </div>
                </div>
                <div className="lightbox-btn-group">
                    <button
                        id="lightboxRegenerateBtn"
                        className={`lightbox-btn ${isLoading ? 'loading' : ''}`}
                        onClick={handleRegenerate}
                        disabled={isLoading}
                        title="Регенерировать изображение"
                    >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
                            <path d="M21 3v5h-5" />
                            <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
                            <path d="M3 21v-5h5" />
                        </svg>
                        <span>{isLoading ? 'Генерация...' : 'Регенерировать'}</span>
                    </button>
                    <button
                        id="lightboxDownloadBtn"
                        className="lightbox-btn"
                        onClick={handleDownload}
                        disabled={isLoading}
                        title="Скачать изображение"
                    >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                            <polyline points="7 10 12 15 17 10" />
                            <line x1="12" x2="12" y1="15" y2="3" />
                        </svg>
                        <span>Скачать</span>
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ImageLightbox;
