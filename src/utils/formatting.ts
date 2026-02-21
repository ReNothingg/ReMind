import MarkdownIt from 'markdown-it';
import DOMPurify from 'dompurify';
import Prism from 'prismjs';
import 'prismjs/plugins/line-numbers/prism-line-numbers'; // Import CSS for this too if needed
import katex from 'katex';

export const escapeHtml = (unsafe) => {
    return (unsafe || '')
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
};

const buildDiagramBlock = ({ language, filename, codeContent }) => {
    const normalizedLanguage = language === 'd3' ? 'd3js' : (language === 'mmd' ? 'mermaid' : language);
    const diagramMeta = {
        chartjs: {
            label: 'Chart.js',
            blockClass: 'chartjs-block',
            preview: `
                <div class="diagram-pan-surface chart-container loading">
                    <canvas class="diagram-pan-target" role="img" aria-label="Chart.js diagram"></canvas>
                    <div class="chart-loading">Загрузка графика...</div>
                    <div class="chart-error" aria-live="polite"></div>
                </div>
            `,
            codeLanguage: 'json'
        },
        d3js: {
            label: 'D3.js',
            blockClass: 'd3js-block',
            preview: `
                <div class="diagram-pan-surface d3-container loading">
                    <div class="d3-visualization diagram-pan-target" role="img" aria-label="D3 diagram"></div>
                    <div class="d3-loading">Загрузка визуализации...</div>
                    <div class="d3-error" aria-live="polite"></div>
                </div>
            `,
            codeLanguage: 'json'
        },
        nomnoml: {
            label: 'Nomnoml',
            blockClass: 'nomnoml-block',
            preview: `
                <div class="diagram-pan-surface nomnoml-container loading">
                    <div class="nomnoml-visualization diagram-pan-target" role="img" aria-label="Nomnoml diagram"></div>
                    <div class="nomnoml-loading">Загрузка схемы...</div>
                    <div class="nomnoml-error" aria-live="polite"></div>
                </div>
            `
        },
        mermaid: {
            label: 'Mermaid',
            blockClass: 'mermaid-block',
            preview: `
                <div class="diagram-pan-surface mermaid-container loading">
                    <div class="mermaid-visualization diagram-pan-target" role="img" aria-label="Mermaid diagram"></div>
                    <div class="mermaid-loading">Загрузка схемы...</div>
                    <div class="mermaid-error" aria-live="polite"></div>
                </div>
            `,
            codeLanguage: 'mermaid'
        }
    };

    const meta = diagramMeta[normalizedLanguage];
    if (!meta) return null;

    const displayName = filename || meta.label;
    const safeName = escapeHtml(displayName);
    const escapedContent = escapeHtml(codeContent);
    const codeLanguage = meta.codeLanguage || normalizedLanguage;
    const previewMarkup = typeof meta.preview === 'function' ? meta.preview({ escapedContent }) : meta.preview;

    return `
    <div class="code-block diagram-block ${meta.blockClass}" data-language="${normalizedLanguage}" data-filename="${safeName}">
        <div class="code-block-header">
            <span class="code-block-icon">&lt;/&gt;</span>
            <span class="code-block-filename">${safeName}</span>
            <div class="code-block-tabs" role="tablist" aria-label="Диаграмма">
                <button class="code-tab-btn active" data-tab="preview" type="button">Предпросмотр</button>
                <button class="code-tab-btn" data-tab="code" type="button">Код</button>
            </div>
            <div class="code-block-header-actions">
                <button class="download-code-btn" title="Скачать файл"><img src=" /icons/ui/download.svg" alt="Download"></button>
                <button class="copy-code-btn" title="Скопировать код"><img src=" /icons/ui/copy.svg" alt="Copy"></button>
                <button class="toggle-code-btn" title="Развернуть">
                    <svg class="icon-expand" viewBox="0 0 24 24" fill="currentColor" width="18px" height="18px" style="display: block;"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>
                    <svg class="icon-collapse" viewBox="0 0 24 24" fill="currentColor" width="18px" height="18px" style="display: none;"><path d="M7.41 15.41L12 10.83l4.59 4.58L18 14l-6-6-6 6 1.41 1.41z"/></svg>
                </button>
            </div>
        </div>
        <div class="code-block-pane diagram-preview active" data-pane="preview">
            ${previewMarkup}
        </div>
        <div class="code-block-pane code-block-scroll-wrapper" data-pane="code">
            <div class="code-block-content">
                <pre class="line-numbers language-${codeLanguage}"><code class="language-${codeLanguage}">${escapedContent}</code></pre>
            </div>
        </div>
    </div>`;
};
const md = new MarkdownIt({
    html: true,
    linkify: true,
    typographer: true,
});
const originalRender = md.render.bind(md);
md.render = function (str, env) {
    let toRender = str.replace(/\\\[([\s\S]+?)\\\]/g, (m, expr) => `$$${expr}$$`)
        .replace(/\\\(([^\n]+?)\\\)/g, (m, expr) => `$${expr}$`);
    let html = originalRender(toRender, env);
    try {
        html = html.replace(/\$\$([\s\S]+?)\$\$/g, (m, expr) =>
            katex.renderToString(expr, { displayMode: true, throwOnError: false })
        );
        html = html.replace(/\$([^$\n]+?)\$/g, (m, expr) =>
            katex.renderToString(expr, { displayMode: false, throwOnError: false })
        );
    } catch (e) {
        console.warn('KaTeX render failed', e);
    }
    return html;
};
md.renderer.rules.fence = (tokens, idx) => {
    const token = tokens[idx];
    const codeContent = token.content;
    const languageHint = token.info ? md.utils.unescapeAll(token.info).trim() : '';
    let actualLanguage = 'plaintext';
    let filename = '';

    if (languageHint.includes(':')) {
        const parts = languageHint.split(':', 2);
        actualLanguage = parts[0].trim().toLowerCase() || 'plaintext';
        filename = parts[1].trim();
    } else {
        actualLanguage = languageHint.trim().toLowerCase() || 'plaintext';
    }

    if (['beatbox', 'quiz', 'spinwheel'].includes(actualLanguage)) {
        const escapedState = escapeHtml(codeContent);
        return `<div class="${actualLanguage}-instance-host" data-${actualLanguage}-state='${escapedState}'></div>`;
    }

    const diagramBlock = buildDiagramBlock({
        language: actualLanguage,
        filename,
        codeContent
    });
    if (diagramBlock) {
        return diagramBlock;
    }
    if (!filename) {
        filename = actualLanguage === 'plaintext' ? "Code Snippet" : (actualLanguage.charAt(0).toUpperCase() + actualLanguage.slice(1));
    }
    const escapedContent = escapeHtml(codeContent);
    return `
    <div class="code-block" data-language="${actualLanguage}" data-filename="${filename}">
        <div class="code-block-header">
            <span class="code-block-icon">&lt;/&gt;</span>
            <span class="code-block-filename">${filename}</span>
            <div class="code-block-header-actions">
                <button class="download-code-btn" title="Скачать файл"><img src=" /icons/ui/download.svg" alt="Download"></button>
                <button class="copy-code-btn" title="Скопировать код"><img src=" /icons/ui/copy.svg" alt="Copy"></button>
                <button class="toggle-code-btn" title="Развернуть">
                    <svg class="icon-expand" viewBox="0 0 24 24" fill="currentColor" width="18px" height="18px" style="display: block;"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>
                    <svg class="icon-collapse" viewBox="0 0 24 24" fill="currentColor" width="18px" height="18px" style="display: none;"><path d="M7.41 15.41L12 10.83l4.59 4.58L18 14l-6-6-6 6 1.41 1.41z"/></svg>
                </button>
            </div>
        </div>
        <div class="code-block-scroll-wrapper">
            <div class="code-block-content">
                <pre class="line-numbers language-${actualLanguage}"><code class="language-${actualLanguage}">${escapedContent}</code></pre>
            </div>
        </div>
    </div>`;
};
const processInteractiveHTMLTags = (text) => {
    if (typeof text !== 'string' || !text) return text;

    const makePlaceholder = (toolName) => {
        const name = (toolName || '').toLowerCase();
        const label = `Создание ${name}`;
        return `<span class="interactive-placeholder" data-tool="${name}" aria-live="polite"><span class="ip-spinner"></span><span class="ip-text">${label}</span></span>`;
    };

    const unclosedConfigs = [
        { tag: 'beatbox' },
        { tag: 'quiz' },
        { tag: 'spinwheel' }
    ];

    for (const cfg of unclosedConfigs) {
        const openTag = new RegExp(`<${cfg.tag}>`, 'i');
        const closeTag = new RegExp(`</${cfg.tag}>`, 'i');
        if (openTag.test(text) && !closeTag.test(text)) {
            const lastOpenIdx = text.toLowerCase().lastIndexOf(`<${cfg.tag}>`);
            if (lastOpenIdx !== -1) {
                const head = text.slice(0, lastOpenIdx);
                text = `${head}${makePlaceholder(cfg.tag)}`;
            }
        }
    }

    const escapeHtml = (unsafe) => {
        return unsafe
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    };
    const toBase64 = (str) => {
        try {
            return btoa(unescape(encodeURIComponent(str)));
        } catch (e) {
            console.warn('Base64 encoding failed:', e);
            return '';
        }
    };

    text = text.replace(/<beatbox>([\s\S]*?)<\/beatbox>/gi, (match, content) => {
        const encodedState = toBase64(content.trim());
        return `<div class="beatbox-instance-host" data-beatbox-state-b64='${encodedState}'></div>`;
    });

    text = text.replace(/<quiz>([\s\S]*?)<\/quiz>/gi, (match, content) => {
        const encodedState = toBase64(content.trim());
        return `<div class="quiz-instance-host" data-quiz-state-b64='${encodedState}'></div>`;
    });

    text = text.replace(/<spinwheel>([\s\S]*?)<\/spinwheel>/gi, (match, content) => {
        const encodedState = toBase64(content.trim());
        return `<div class="spinwheel-instance-host" data-spinwheel-state-b64='${encodedState}'></div>`;
    });
    text = text.replace(/<think(?:\s+data-open="(\d+)")?(?:\s+data-close="(\d+)")?>([\s\S]*?)<\/think>/gi, (match, openTime, closeTime, content) => {
        const now = Date.now();
        const open = openTime ? parseInt(openTime, 10) : now;
        const close = closeTime ? parseInt(closeTime, 10) : now;

        const escapedContent = escapeHtml(content.trim());
        return `<div class="think-instance-host" data-think-open="${open}" data-think-close="${close}" data-think-content='${escapedContent}'></div>`;
    });
    const unclosedThink = /<think(?:\s+data-open="(\d+)")?(?:\s+data-close="(\d+)?")?>/gi;
    if (unclosedThink.test(text)) {
        text = text.replace(unclosedThink, '');
    }

    return text;
};

export const formatText = (text) => {
    if (!text) return '';
    let processedText = processInteractiveHTMLTags(text);
    processedText = processedText.replace(/\\\[([\s\S]+?)\\\]/g, (m, expr) => `$$${expr}$$`)
        .replace(/\\\(([^\n]+?)\\\)/g, (m, expr) => `$${expr}$`);

    let renderedHtml = md.render(processedText);
    renderedHtml = renderedHtml
        .replace(/<li>\[ \] /g, '<li class="task-list-item"><input type="checkbox" name="task_item" disabled> ')
        .replace(/<li>\[x\] /g, '<li class="task-list-item"><input type="checkbox" name="task_item" checked disabled> ');
    renderedHtml = renderedHtml.replace(/<table>/g, (match) => {
        return '<div class="table-wrapper"><button class="table-copy-btn" type="button" title="Копировать таблицу"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg></button><div><table>';
    });
    renderedHtml = renderedHtml.replace(/<\/table>/g, '</table></div></div>');
    return DOMPurify.sanitize(renderedHtml, {
        ADD_TAGS: ['svg', 'path', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'div', 'span', 'button', 'img', 'input', 'model-viewer', 'canvas'],
        ADD_ATTR: [
            'class', 'title', 'alt', 'viewBox', 'fill', 'width', 'height', 'd',
            'data-tab', 'data-pane', 'scope', 'colspan', 'rowspan',
            'type', 'checked', 'disabled', 'src', 'name',
            'data-beatbox-state', 'data-beatbox-state-b64', 'data-quiz-state', 'data-quiz-state-b64', 'data-spinwheel-state', 'data-spinwheel-state-b64',
            'data-livebeatbox', 'data-livequiz', 'data-livespinwheel',
            'data-think-open', 'data-think-close', 'data-think-content',
            'data-tool', 'aria-live', 'aria-label', 'role', 'stroke-width',
            'camera-controls', 'auto-rotate', 'shadow-intensity', 'environment-image', 'exposure'
        ]
    });
};

export const formatPlainText = (text) => {
    if (!text) return '';
    return escapeHtml(text).replace(/\n/g, '<br>');
};

const userMd = new MarkdownIt({
    html: false,
    linkify: true,
    typographer: true,
});

userMd.renderer.rules.fence = (tokens, idx) => {
    const token = tokens[idx];
    const codeContent = token.content || '';
    const languageHint = token.info ? userMd.utils.unescapeAll(token.info).trim() : '';

    let actualLanguage = 'plaintext';
    let filename = '';

    if (languageHint.includes(':')) {
        const parts = languageHint.split(':', 2);
        actualLanguage = parts[0].trim().toLowerCase() || 'plaintext';
        filename = parts[1].trim();
    } else {
        actualLanguage = languageHint.trim().toLowerCase() || 'plaintext';
    }

    const diagramBlock = buildDiagramBlock({
        language: actualLanguage,
        filename,
        codeContent
    });
    if (diagramBlock) {
        return diagramBlock;
    }

    if (!filename) {
        filename = actualLanguage === 'plaintext' ? "Code Snippet" : (actualLanguage.charAt(0).toUpperCase() + actualLanguage.slice(1));
    }

    const escapedContent = escapeHtml(codeContent);

    return `
    <div class="code-block" data-language="${actualLanguage}" data-filename="${filename}">
        <div class="code-block-header">
            <span class="code-block-icon">&lt;/&gt;</span>
            <span class="code-block-filename">${escapeHtml(filename)}</span>
            <div class="code-block-header-actions">
                <button class="download-code-btn" title="Скачать файл"><img src=" /icons/ui/download.svg" alt="Download"></button>
                <button class="copy-code-btn" title="Скопировать код"><img src=" /icons/ui/copy.svg" alt="Copy"></button>
                <button class="toggle-code-btn" title="Развернуть">
                    <svg class="icon-expand" viewBox="0 0 24 24" fill="currentColor" width="18px" height="18px" style="display: block;"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>
                    <svg class="icon-collapse" viewBox="0 0 24 24" fill="currentColor" width="18px" height="18px" style="display: none;"><path d="M7.41 15.41L12 10.83l4.59 4.58L18 14l-6-6-6 6 1.41 1.41z"/></svg>
                </button>
            </div>
        </div>
        <div class="code-block-scroll-wrapper">
            <div class="code-block-content">
                <pre class="line-numbers"><code class="language-${escapeHtml(actualLanguage)}">${escapedContent}</code></pre>
            </div>
        </div>
    </div>`;
};

export const formatUserText = (text) => {
    if (!text) return '';
    const renderedHtml = userMd.render(text);
    return DOMPurify.sanitize(renderedHtml, {
        ADD_TAGS: ['svg', 'path', 'div', 'span', 'button', 'img', 'input', 'pre', 'code', 'canvas'],
        ADD_ATTR: [
            'class', 'title', 'alt', 'viewBox', 'fill', 'width', 'height', 'd',
            'type', 'checked', 'disabled', 'src', 'name',
            'data-language', 'data-filename', 'data-tab', 'data-pane',
            'aria-label', 'role', 'aria-live',
        ]
    });
};

export const highlightCode = () => {
    Prism.highlightAll();
};
