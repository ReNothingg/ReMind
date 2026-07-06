export const API_BASE_URL = (() => {
    const hostname = window.location.hostname;

    if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '0.0.0.0') {
        return '';
    }

    return window.location.origin;
})();

export const ALLOW_GUEST_CHATS_SAVE = false;

export const TEXT_FILE_EXTENSIONS = ['txt', 'py', 'js', 'html', 'css', 'json', 'cpp', 'c', 'cs', 'java', 'php', 'rb', 'swift', 'kt', 'go', 'rs', 'ts', 'md', 'xml', 'yaml', 'yml', 'sh', 'bat', 'ps1', 'pl', 'dart', 'lua', 'r', 'scala', 'hs', 'erl', 'clj', 'ex', 'zig', 'ino'];

export const IMAGE_FILE_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'];

export const VALID_IMAGE_MIME_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml'];

export const SERIOUS_ERROR_KEYPHRASES = ["failed to fetch", "networkerror", "сервер недоступен", "ошибка сети"];
