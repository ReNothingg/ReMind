import React, { useState, useEffect, useRef } from 'react';
import { apiService } from '../../services/api';
import { Utils } from '../../utils/utils';
import ModalShell from '../UI/ModalShell';
import { cn } from '../../utils/cn';

const ImageLightbox = ({ isOpen, imageSrc, messageElement, onClose, currentModel, sessionId }) => {
    const [isLoading, setIsLoading] = useState(false);
    const [currentImageSrc, setCurrentImageSrc] = useState(imageSrc);
    const [imageStyle, setImageStyle] = useState('realistic');
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
            Utils.showPopupWarning?.('РќРµ РЅР°Р№РґРµРЅРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРѕРµ СЃРѕРѕР±С‰РµРЅРёРµ РґР»СЏ СЂРµРіРµРЅРµСЂР°С†РёРё.');
            return;
        }

        const userMessageText = userMessageElement.dataset?.rawContent || userMessageElement.textContent || '';
        if (!userMessageText.trim()) {
            Utils.showPopupWarning?.('РќРµС‚ С‚РµРєСЃС‚Р° РґР»СЏ СЂРµРіРµРЅРµСЂР°С†РёРё РёР·РѕР±СЂР°Р¶РµРЅРёСЏ.');
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
                throw new Error('РЎРµСЂРІРµСЂ РЅРµ РІРµСЂРЅСѓР» РЅРѕРІРѕРµ РёР·РѕР±СЂР°Р¶РµРЅРёРµ.');
            }

            const fullUrl = imagePath.startsWith('http') ? imagePath : `${apiService.baseURL}${imagePath}`;
            setCurrentImageSrc(fullUrl);
            const imgEl = messageElement.querySelector('.attached-img');
            if (imgEl) {
                imgEl.src = fullUrl;
            }
        } catch (error) {
            console.error('Failed to regenerate image:', error);
            Utils.showPopupWarning?.(`РќРµ СѓРґР°Р»РѕСЃСЊ СЂРµРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ РёР·РѕР±СЂР°Р¶РµРЅРёРµ: ${error.message}`);
        } finally {
            setIsLoading(false);
        }
    };

    const handleDownload = async () => {
        if (!currentImageSrc) {
            Utils.showPopupWarning?.('РќРµС‚ РёР·РѕР±СЂР°Р¶РµРЅРёСЏ РґР»СЏ СЃРєР°С‡РёРІР°РЅРёСЏ.');
            return;
        }

        try {
            const response = await fetch(currentImageSrc);
            if (!response.ok) throw new Error(`РћС€РёР±РєР° СЃРµС‚Рё: ${response.statusText}`);
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
            } catch (_err) { }
            a.download = `remind-art-${Date.now()}.${ext}`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            a.remove();
        } catch (error) {
            console.error('РћС€РёР±РєР° СЃРєР°С‡РёРІР°РЅРёСЏ РёР·РѕР±СЂР°Р¶РµРЅРёСЏ:', error);
            Utils.showPopupWarning?.('РќРµ СѓРґР°Р»РѕСЃСЊ СЃРєР°С‡Р°С‚СЊ РёР·РѕР±СЂР°Р¶РµРЅРёРµ. РџРѕРїСЂРѕР±СѓР№С‚Рµ СЃРѕС…СЂР°РЅРёС‚СЊ РµРіРѕ С‡РµСЂРµР· РєРѕРЅС‚РµРєСЃС‚РЅРѕРµ РјРµРЅСЋ (РїСЂР°РІС‹Р№ РєР»РёРє).');
            window.open(currentImageSrc, '_blank');
        }
    };

    if (!isOpen) return null;

    return (
        <ModalShell
            className="image-lightbox active px-3 py-4 sm:px-5 sm:py-8"
            contentClassName="w-full max-w-[min(92vw,1200px)] overflow-visible border-transparent bg-transparent shadow-none"
            onBackdropClick={onClose}
        >
            <div className="lightbox-image-wrapper relative flex min-h-[50vh] items-center justify-center rounded-[28px] border border-white/10 bg-black/30 p-4 shadow-[0_24px_80px_rgba(0,0,0,0.45)] backdrop-blur-sm">
                <img
                    ref={imageRef}
                    id="lightboxImage"
                    className="lightbox-image max-h-[70vh] w-auto max-w-full rounded-[20px] object-contain"
                    src={currentImageSrc}
                    alt="Lightbox"
                />
                <div
                    className={cn(
                        'lightbox-loader absolute inset-0 flex items-center justify-center rounded-[28px] bg-black/35 opacity-0 transition duration-200 ease-out',
                        isLoading && 'visible opacity-100'
                    )}
                >
                    <div className="spinner size-10 animate-spin rounded-full border-2 border-white/25 border-t-white" />
                </div>
            </div>

            <button
                className="lightbox-close-btn ui-icon-control absolute right-0 top-0 z-10 size-11 -translate-y-1/2 translate-x-1/2 rounded-full border-white/15 bg-black/45 text-white hover:bg-black/60"
                onClick={onClose}
                aria-label="Р—Р°РєСЂС‹С‚СЊ"
                type="button"
            >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
            </button>

            <div className="lightbox-controls mt-4 flex flex-col gap-3 rounded-2xl border border-white/10 bg-black/35 p-4 text-white backdrop-blur-sm md:flex-row md:items-center md:justify-between">
                <div className="lightbox-style-group">
                    <div className="lightbox-select-wrapper">
                        <select
                            id="lightboxStyleSelect"
                            value={imageStyle}
                            onChange={(e) => setImageStyle(e.target.value)}
                            disabled={isLoading}
                            className="min-w-52 rounded-xl border border-white/15 bg-white/8 px-3 py-2.5 text-sm font-medium text-white outline-none transition duration-200 ease-out hover:bg-white/12 focus:border-white/30 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            <option value="realistic">Р РµР°Р»РёСЃС‚РёС‡РЅС‹Р№</option>
                            <option value="cartoon">РњСѓР»СЊС‚СЏС€РЅС‹Р№</option>
                            <option value="anime">РђРЅРёРјРµ</option>
                            <option value="oil_painting">РњР°СЃР»СЏРЅР°СЏ Р¶РёРІРѕРїРёСЃСЊ</option>
                            <option value="watercolor">РђРєРІР°СЂРµР»СЊ</option>
                            <option value="pencil_sketch">РљР°СЂР°РЅРґР°С€РЅС‹Р№ РЅР°Р±СЂРѕСЃРѕРє</option>
                        </select>
                    </div>
                </div>

                <div className="lightbox-btn-group flex flex-col gap-2 sm:flex-row">
                    <button
                        id="lightboxRegenerateBtn"
                        className={cn(
                            'lightbox-btn inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-semibold transition duration-200 ease-out',
                            isLoading
                                ? 'loading border-white/12 bg-white/8 text-white/70'
                                : 'border-white/15 bg-white/10 text-white hover:bg-white/16'
                        )}
                        onClick={handleRegenerate}
                        disabled={isLoading}
                        title="Р РµРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ РёР·РѕР±СЂР°Р¶РµРЅРёРµ"
                        type="button"
                    >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
                            <path d="M21 3v5h-5" />
                            <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
                            <path d="M3 21v-5h5" />
                        </svg>
                        <span>{isLoading ? 'Р“РµРЅРµСЂР°С†РёСЏ...' : 'Р РµРіРµРЅРµСЂРёСЂРѕРІР°С‚СЊ'}</span>
                    </button>
                    <button
                        id="lightboxDownloadBtn"
                        className="lightbox-btn inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-white/15 bg-white/10 px-4 py-2.5 text-sm font-semibold text-white transition duration-200 ease-out hover:bg-white/16"
                        onClick={handleDownload}
                        disabled={isLoading}
                        title="РЎРєР°С‡Р°С‚СЊ РёР·РѕР±СЂР°Р¶РµРЅРёРµ"
                        type="button"
                    >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                            <polyline points="7 10 12 15 17 10" />
                            <line x1="12" x2="12" y1="15" y2="3" />
                        </svg>
                        <span>РЎРєР°С‡Р°С‚СЊ</span>
                    </button>
                </div>
            </div>
        </ModalShell>
    );
};

export default ImageLightbox;
