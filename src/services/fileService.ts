import { IMAGE_FILE_EXTENSIONS, VALID_IMAGE_MIME_TYPES, TEXT_FILE_EXTENSIONS } from '../utils/constants';

const getFileExtension = (file) => {
    const name = typeof file?.name === 'string' ? file.name : typeof file?.original_name === 'string' ? file.original_name : '';
    return name.includes('.') ? name.split('.').pop()?.toLowerCase() || '' : '';
};

const IMAGE_EXTENSION_MIME_TYPES = {
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    png: 'image/png',
    gif: 'image/gif',
    webp: 'image/webp',
    svg: 'image/svg+xml'
};

const detectImageMimeFromBytes = (bytes) => {
    if (!bytes || bytes.length < 4) return '';

    if (bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) {
        return 'image/png';
    }
    if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
        return 'image/jpeg';
    }
    if (bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x38) {
        return 'image/gif';
    }
    if (
        bytes.length >= 12 &&
        bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46 &&
        bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50
    ) {
        return 'image/webp';
    }

    return '';
};

export const fileService = {
    MAX_FILES: 10,
    TEXT_EXTENSIONS: TEXT_FILE_EXTENSIONS,
    IMAGE_EXTENSIONS: IMAGE_FILE_EXTENSIONS,
    VALID_IMAGE_MIME_TYPES,

    validateFile(file) {
        if (!file) return { valid: false, error: 'Файл отсутствует' };
        const MAX_FILE_SIZE = 100 * 1024 * 1024;
        if (file.size > MAX_FILE_SIZE) {
            return { valid: false, error: `Файл слишком большой. Максимум 100MB.` };
        }

        return { valid: true };
    },

    validateFiles(files) {
        if (!files || files.length === 0) return { valid: false, error: 'Файлы отсутствуют' };

        if (files.length > this.MAX_FILES) {
            return { valid: false, error: `Можно прикрепить не более ${this.MAX_FILES} файлов.` };
        }

        for (const file of files) {
            const validation = this.validateFile(file);
            if (!validation.valid) return validation;
        }

        return { valid: true };
    },

    isTextFile(file) {
        if (!file?.name) return false;
        const extension = getFileExtension(file);
        return file.type?.startsWith('text/') || this.TEXT_EXTENSIONS.includes(extension);
    },

    isImageFile(file) {
        const extension = getFileExtension(file);

        return (
            Boolean(this.getImageMimeType(file)) ||
            this.IMAGE_EXTENSIONS.includes(extension)
        );
    },

    getImageMimeType(file) {
        const mimeType = typeof file?.type === 'string'
            ? file.type
            : (typeof file?.mime_type === 'string' ? file.mime_type : '');
        if (this.VALID_IMAGE_MIME_TYPES.includes(mimeType) || mimeType.startsWith('image/')) {
            return mimeType;
        }

        const extension = getFileExtension(file);
        return IMAGE_EXTENSION_MIME_TYPES[extension] || '';
    },

    async detectImageMimeFromFile(file) {
        if (!file?.slice || typeof file.slice !== 'function') return '';
        try {
            const buffer = await file.slice(0, 12).arrayBuffer();
            return detectImageMimeFromBytes(new Uint8Array(buffer));
        } catch {
            return '';
        }
    },

    normalizeImageDataUrl(dataUrl, mimeType) {
        if (!mimeType || typeof dataUrl !== 'string' || !dataUrl.startsWith('data:')) {
            return dataUrl;
        }
        return dataUrl.replace(/^data:[^;]*;/, `data:${mimeType};`);
    },

    formatFileSize(bytes, decimals = 2) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    },

    getFileIconPath(ext) {
        const iconExtensions = {
            'pdf': 'pdf',
            'doc': 'word',
            'docx': 'word',
            'xls': 'excel',
            'xlsx': 'excel',
            'ppt': 'powerpoint',
            'pptx': 'powerpoint',
            'zip': 'zip',
            'rar': 'zip',
            '7z': 'zip',
            'txt': 'document',
            'json': 'json',
            'js': 'javascript',
            'ts': 'typescript',
            'py': 'python',
            'java': 'java',
            'cpp': 'cpp',
            'c': 'c',
            'html': 'html',
            'css': 'css',
            'xml': 'xml',
            'yaml': 'yaml',
            'yml': 'yaml',
            'sql': 'database',
            'sh': 'shell',
            'bat': 'shell',
            'ps1': 'shell'
        };

        const iconType = iconExtensions[ext] || 'file';
        return `https://cdn.jsdelivr.net/gh/vscode-icons/vscode-icons/icons/${iconType}.svg`;
    },

    escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, m => map[m]);
    }
};
