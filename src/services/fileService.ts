import { VALID_IMAGE_MIME_TYPES, VALID_3D_MODEL_EXTENSIONS, VALID_3D_MODEL_MIME_TYPES, TEXT_FILE_EXTENSIONS } from '../utils/constants';

export const fileService = {
    MAX_FILES: 10,
    TEXT_EXTENSIONS: TEXT_FILE_EXTENSIONS,
    VALID_IMAGE_MIME_TYPES,
    VALID_3D_MODEL_EXTENSIONS,
    VALID_3D_MODEL_MIME_TYPES,

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
        const extension = file.name.split('.').pop()?.toLowerCase() || '';
        return file.type.startsWith('text/') || this.TEXT_EXTENSIONS.includes(extension);
    },

    isImageFile(file) {
        return this.VALID_IMAGE_MIME_TYPES.includes(file.type);
    },

    is3DModelFile(file) {
        if (!file?.name) return false;
        const extension = file.name.split('.').pop()?.toLowerCase() || '';
        return this.VALID_3D_MODEL_EXTENSIONS.includes(extension) ||
            this.VALID_3D_MODEL_MIME_TYPES.includes(file.type);
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
