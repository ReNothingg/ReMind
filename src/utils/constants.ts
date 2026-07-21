export const API_BASE_URL = (() => {
    const hostname = window.location.hostname;

    if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '0.0.0.0') {
        return '';
    }

    return window.location.origin;
})();

export const ALLOW_GUEST_CHATS_SAVE = false;

export const TEXT_FILE_EXTENSIONS = [
    'txt', 'md', 'json', 'csv', 'xml', 'yaml', 'yml',
    'css', 'java', 'rs', 'go', 'ts',
];

export const IMAGE_FILE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp'];

export const VALID_IMAGE_MIME_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];

export const CHAT_UPLOAD_EXTENSIONS = [
    ...IMAGE_FILE_EXTENSIONS,
    ...TEXT_FILE_EXTENSIONS,
];

export const CHAT_UPLOAD_ACCEPT = CHAT_UPLOAD_EXTENSIONS.map((extension) => `.${extension}`).join(',');
export const CHAT_UPLOAD_MAX_FILES = 10;
export const CHAT_UPLOAD_MAX_TOTAL_BYTES = 8 * 1024 * 1024;

export const SERIOUS_ERROR_KEYPHRASES = ["failed to fetch", "networkerror", "сервер недоступен", "ошибка сети"];
