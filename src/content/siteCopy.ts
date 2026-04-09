import { normalizeLanguage } from '../i18n';

type LandingFeature = {
    description: string;
    title: string;
};

type LandingMetric = {
    label: string;
    value: string;
};

type LandingPreviewHighlight = {
    label: string;
    value: string;
};

type LandingPreviewStep = {
    description: string;
    title: string;
};

type SiteCopy = {
    landing: {
        composerHint: string;
        composerTitle: string;
        eyebrow: string;
        features: LandingFeature[];
        metrics: LandingMetric[];
        previewDescription: string;
        previewEyebrow: string;
        previewHighlights: LandingPreviewHighlight[];
        previewSteps: LandingPreviewStep[];
        previewTitle: string;
        samplePrompt: string;
        sampleTitle: string;
        suggestionsHint: string;
        suggestionsTitle: string;
        summary: string;
        title: string;
    };
    metaDescription: string;
    metaKeywords: string;
    sharedChatDescription: string;
    sharedChatTitle: string;
};

const SITE_COPY: Record<'en' | 'ru', SiteCopy> = {
    en: {
        metaDescription: 'AI workspace for long-running chats, file analysis, and shareable sessions.',
        metaKeywords:
            'ReMind, AI workspace, AI chat, file analysis, shared chat, session workspace, Gemini assistant',
        sharedChatTitle: 'Shared chat',
        sharedChatDescription: 'View a shared ReMind conversation in read-only mode.',
        landing: {
            eyebrow: 'AI workspace for chat, files, and session handoff',
            title: 'Turn a blank prompt into a working session.',
            summary:
                'ReMind keeps context, files, and revisions in one thread so you can move from a rough brief to a shareable result without starting over.',
            composerTitle: 'Start with a real brief',
            composerHint:
                'Ask a question, attach files, or paste raw notes below. The thread stays ready for follow-up decisions and revisions.',
            sampleTitle: 'Use a concrete first request',
            samplePrompt:
                'Review this product brief, extract the risks, and turn it into a launch plan with owners and deadlines.',
            suggestionsTitle: 'Start from a real scenario',
            suggestionsHint: 'Pick a prompt below or write your own workflow in the composer.',
            metrics: [
                {
                    value: '1 thread',
                    label: 'for notes, files, and revisions',
                },
                {
                    value: 'inline files',
                    label: 'instead of a separate upload flow',
                },
                {
                    value: 'read-only share',
                    label: 'when the result is ready to hand off',
                },
            ],
            features: [
                {
                    title: 'Keep the whole context alive',
                    description:
                        'Edit prompts, compare answer variants, and continue in the same thread instead of rebuilding context from zero.',
                },
                {
                    title: 'Work directly from source material',
                    description:
                        'Bring in documents and images so the conversation stays attached to the evidence, not to screenshots in another app.',
                },
                {
                    title: 'Hand off without cleanup work',
                    description:
                        'Publish a read-only session when you need async review or a clean link for teammates and clients.',
                },
            ],
            previewEyebrow: 'Session anatomy',
            previewTitle: 'What a strong first run looks like',
            previewDescription:
                'A good opening request turns the chat into an actual workspace instead of a one-shot answer box.',
            previewSteps: [
                {
                    title: 'Load the source',
                    description: 'Attach the brief, screenshots, or raw notes that define the job.',
                },
                {
                    title: 'Ask for structure',
                    description: 'Request summary, risks, options, and next actions in one pass.',
                },
                {
                    title: 'Refine and share',
                    description: 'Keep editing in the same session, then send a read-only link when it is ready.',
                },
            ],
            previewHighlights: [
                {
                    label: 'Input',
                    value: 'brief, assets, constraints',
                },
                {
                    label: 'Output',
                    value: 'summary, blockers, launch plan',
                },
                {
                    label: 'Handoff',
                    value: 'thread you can revisit tomorrow',
                },
            ],
        },
    },
    ru: {
        metaDescription: 'AI-рабочее пространство для длинных диалогов, анализа файлов и общих сессий.',
        metaKeywords:
            'ReMind, AI workspace, AI chat, анализ файлов, история чатов, общие ссылки, рабочая сессия, Gemini ассистент',
        sharedChatTitle: 'Публичный чат',
        sharedChatDescription: 'Откройте shared-сессию ReMind в режиме только для чтения.',
        landing: {
            eyebrow: 'AI-рабочее пространство для диалогов, файлов и передачи результата',
            title: 'Превратите пустой промпт в рабочую сессию.',
            summary:
                'ReMind держит контекст, файлы и правки в одном треде, чтобы вы шли от сырого брифа к готовому результату без перезапуска диалога.',
            composerTitle: 'Загрузите реальную задачу',
            composerHint:
                'Задайте вопрос, приложите файлы или вставьте сырые заметки ниже. Тред останется готовым для следующих решений и итераций.',
            sampleTitle: 'Начните с конкретного запроса',
            samplePrompt:
                'Разбери этот продуктовый бриф, выдели риски и собери план запуска с ответственными и сроками.',
            suggestionsTitle: 'Начните с живого сценария',
            suggestionsHint: 'Выберите готовый запрос ниже или сразу опишите свой workflow в поле ввода.',
            metrics: [
                {
                    value: '1 тред',
                    label: 'для заметок, файлов и правок',
                },
                {
                    value: 'файлы внутри',
                    label: 'а не в отдельном upload-flow',
                },
                {
                    value: 'read-only ссылка',
                    label: 'когда результат уже можно передать',
                },
            ],
            features: [
                {
                    title: 'Контекст остаётся живым',
                    description:
                        'Редактируйте запросы, сравнивайте варианты ответа и продолжайте в той же сессии вместо постоянного старта с нуля.',
                },
                {
                    title: 'Работайте прямо от исходников',
                    description:
                        'Документы и изображения остаются частью обсуждения, а не расползаются по другим приложениям и скриншотам.',
                },
                {
                    title: 'Передавайте результат без уборки',
                    description:
                        'Публикуйте read-only сессию, когда нужен асинхронный ревью, согласование или аккуратная ссылка для клиента.',
                },
            ],
            previewEyebrow: 'Анатомия сессии',
            previewTitle: 'Как выглядит сильный первый заход',
            previewDescription:
                'Хороший стартовый запрос превращает чат в рабочее пространство, а не в поле для одноразового ответа.',
            previewSteps: [
                {
                    title: 'Загрузите исходники',
                    description: 'Добавьте бриф, скриншоты или сырые заметки, которые задают контекст.',
                },
                {
                    title: 'Попросите структуру',
                    description: 'Сразу запросите summary, риски, варианты решения и следующие шаги.',
                },
                {
                    title: 'Доведите и поделитесь',
                    description: 'Правьте в той же сессии и отправляйте read-only ссылку, когда результат готов.',
                },
            ],
            previewHighlights: [
                {
                    label: 'Вход',
                    value: 'бриф, материалы, ограничения',
                },
                {
                    label: 'Выход',
                    value: 'summary, blockers, план запуска',
                },
                {
                    label: 'Передача',
                    value: 'тред, к которому можно вернуться завтра',
                },
            ],
        },
    },
};

const OG_LOCALE_BY_LANGUAGE: Record<string, string> = {
    ar: 'ar_AR',
    bn: 'bn_BD',
    en: 'en_US',
    es: 'es_ES',
    fr: 'fr_FR',
    hi: 'hi_IN',
    pt: 'pt_PT',
    ru: 'ru_RU',
    zh: 'zh_CN',
};

export function getSiteCopy(language?: string): SiteCopy {
    const normalized = normalizeLanguage(language);
    if (normalized === 'ru') {
        return SITE_COPY.ru;
    }

    return SITE_COPY.en;
}

export function getOgLocale(language?: string): string {
    const normalized = normalizeLanguage(language);
    return OG_LOCALE_BY_LANGUAGE[normalized] || OG_LOCALE_BY_LANGUAGE.en;
}

export function getDocumentDirection(language?: string): 'ltr' | 'rtl' {
    return normalizeLanguage(language) === 'ar' ? 'rtl' : 'ltr';
}
