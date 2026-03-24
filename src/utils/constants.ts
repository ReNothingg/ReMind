export const API_BASE_URL = (() => {
    const hostname = window.location.hostname;

    if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '0.0.0.0') {
        return '';
    }

    return window.location.origin;
})();

export const ALLOW_GUEST_CHATS_SAVE = false;

export const THINKING_PLACEHOLDERS = [
    "Думаю", "Еще чуть-чуть", "Рассуждаю", "Собираю мысли", "Ищу смысл", "Прокладываю связи",
    "Формирую идею", "Задаю контекст", "Строю гипотезу", "Навожу резкость", "Разворачиваю мысль",
    "Уточняю детали", "Оцениваю варианты", "Связываю точки", "Исследую глубже", "Мыслю иначе",
    "Подключаю интуицию", "Ныряю в суть", "Синхронизирую сознание", "Танцую с абстракциями"
];

export const DEFAULT_WELCOME_MESSAGES = ["Добро пожаловать!", "Привет! Чем могу помочь сегодня?", "Начните диалог, задав вопрос."];
export const DEFAULT_WARNING_PHRASES = ["ReMind может допускать ошибки."];

export const TEXT_FILE_EXTENSIONS = ['txt', 'py', 'js', 'html', 'css', 'json', 'cpp', 'c', 'cs', 'java', 'php', 'rb', 'swift', 'kt', 'go', 'rs', 'ts', 'md', 'xml', 'yaml', 'yml', 'sh', 'bat', 'ps1', 'pl', 'dart', 'lua', 'r', 'scala', 'hs', 'erl', 'clj', 'ex', 'zig', 'ino'];

export const VALID_IMAGE_MIME_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/svg+xml'];

export const INITIAL_CODE_BLOCK_MAX_HEIGHT = '200px';

export const MODEL_DESCRIPTIONS = {
    mind1: 'Самая глупая модель. Имеет лишь несколько фраз для ответов.',
    mind2: 'Экспериментальная модель. Нет цензуры.',
    gemini: 'Gemini от Google. Универсальная модель для текста и изображений.',
    mindart: 'Специализированная модель для создания изображений.',
    mind3: 'Мощная модель для сложных задач.',
    debugger: 'Отладчик состояния элементов с сайта.',
    echo: 'Эхо-бот: повторяет сообщение пользователя.',
    mind4: 'Быстрая модель для первичной обработки.',
};

export const SERIOUS_ERROR_KEYPHRASES = ["failed to fetch", "networkerror", "сервер недоступен", "ошибка сети"];
