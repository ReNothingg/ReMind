import MarkdownIt from 'markdown-it';
import DOMPurify from 'dompurify';
import Prism from 'prismjs';
import 'prismjs/components/prism-markup-templating';
import 'prismjs/components/prism-bash';
import 'prismjs/components/prism-c';
import 'prismjs/components/prism-cpp';
import 'prismjs/components/prism-csharp';
import 'prismjs/components/prism-diff';
import 'prismjs/components/prism-docker';
import 'prismjs/components/prism-git';
import 'prismjs/components/prism-go';
import 'prismjs/components/prism-graphql';
import 'prismjs/components/prism-ini';
import 'prismjs/components/prism-java';
import 'prismjs/components/prism-json';
import 'prismjs/components/prism-jsx';
import 'prismjs/components/prism-kotlin';
import 'prismjs/components/prism-lua';
import 'prismjs/components/prism-makefile';
import 'prismjs/components/prism-markdown';
import 'prismjs/components/prism-nginx';
import 'prismjs/components/prism-php';
import 'prismjs/components/prism-powershell';
import 'prismjs/components/prism-protobuf';
import 'prismjs/components/prism-properties';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-r';
import 'prismjs/components/prism-regex';
import 'prismjs/components/prism-ruby';
import 'prismjs/components/prism-rust';
import 'prismjs/components/prism-scss';
import 'prismjs/components/prism-sql';
import 'prismjs/components/prism-swift';
import 'prismjs/components/prism-toml';
import 'prismjs/components/prism-typescript';
import 'prismjs/components/prism-tsx';
import 'prismjs/components/prism-yaml';
import 'prismjs/plugins/line-numbers/prism-line-numbers';
import katex from 'katex';

if (typeof window !== 'undefined') {
    window.Prism = Prism;
}

const escapeHtml = (unsafe: string | null | undefined) => {
    return (unsafe || '')
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
};

const MAX_LATEX_EXPRESSION_CHARS = 20_000;

const decodeHtmlEntities = (value: string) => value
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&amp;/g, '&');

const renderLatexExpression = (source: string, displayMode: boolean, fallback: string) => {
    const expression = decodeHtmlEntities(source).trim();
    if (!expression || expression.length > MAX_LATEX_EXPRESSION_CHARS) {
        return fallback;
    }

    try {
        const rendered = katex.renderToString(expression, {
            displayMode,
            throwOnError: false,
            trust: false,
            maxExpand: 1_000,
        });
        return `<span class="markdown-latex-source" data-latex-source="${escapeHtml(expression)}" data-latex-display="${displayMode ? 'true' : 'false'}"${displayMode ? ' tabindex="0"' : ''}>${rendered}</span>`;
    } catch (error) {
        console.warn('KaTeX render failed', error);
        return fallback;
    }
};

const renderLatexInHtml = (html: string) => {
    const protectedTags: string[] = [];
    return html.split(/(<[^>]+>)/g).map((segment) => {
        const closingTag = segment.match(/^<\s*\/\s*(pre|code|script|style)\s*>/i);
        if (closingTag) {
            const index = protectedTags.lastIndexOf(String(closingTag[1] || '').toLowerCase());
            if (index >= 0) {
                protectedTags.splice(index, 1);
            }
            return segment;
        }

        const openingTag = segment.match(/^<\s*(pre|code|script|style)\b/i);
        if (openingTag && !/\/\s*>$/.test(segment)) {
            protectedTags.push(String(openingTag[1] || '').toLowerCase());
            return segment;
        }
        if (segment.startsWith('<') || protectedTags.length > 0) {
            return segment;
        }

        const withDisplayMath = segment.replace(
            /\$\$([\s\S]+?)\$\$/g,
            (match, expression) => renderLatexExpression(expression, true, match),
        );
        return withDisplayMath.replace(
            /\$([^$\n]+?)\$/g,
            (match, expression) => renderLatexExpression(expression, false, match),
        );
    }).join('');
};

const linkifyEscapedText = (escapedText: string) => {
    return escapedText.replace(/https?:\/\/[^\s<]+/g, (rawUrl) => {
        const trailingMatch = rawUrl.match(/[.,!?;:)\]]+$/);
        const trailing = trailingMatch ? trailingMatch[0] : '';
        const url = trailing ? rawUrl.slice(0, -trailing.length) : rawUrl;

        if (!url) {
            return rawUrl;
        }

        return `<a class="link-enhanced" href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>${trailing}`;
    });
};

export const stripThinkingBlocks = (text: string | null | undefined): string => {
    if (!text) return '';

    return text
        .replace(/<think(?:\s[^>]*)?>[\s\S]*?<\/think\s*>/gi, '')
        .replace(/<think(?:\s[^>]*)?>[\s\S]*$/gi, '')
        .trim();
};

const CODE_LANGUAGE_ALIASES: Record<string, string> = {
    'c++': 'cpp',
    'c#': 'csharp',
    html: 'markup',
    xml: 'markup',
    svg: 'markup',
    js: 'javascript',
    mjs: 'javascript',
    cjs: 'javascript',
    jsx: 'jsx',
    ts: 'typescript',
    mts: 'typescript',
    cts: 'typescript',
    tsx: 'tsx',
    py: 'python',
    rb: 'ruby',
    rs: 'rust',
    sh: 'bash',
    shell: 'bash',
    shellscript: 'bash',
    zsh: 'bash',
    ps1: 'powershell',
    psm1: 'powershell',
    md: 'markdown',
    yml: 'yaml',
    jsonc: 'json',
    conf: 'nginx',
    env: 'properties',
    gql: 'graphql',
    kt: 'kotlin',
    kts: 'kotlin',
    makefile: 'makefile',
    plist: 'markup',
    plistxml: 'markup',
    proto: 'protobuf',
    ps: 'powershell',
    rlang: 'r',
    scss: 'scss',
    swift: 'swift',
    toml: 'toml',
    dockerfile: 'docker',
    none: 'plaintext',
    plaintext: 'plaintext',
    text: 'plaintext',
    txt: 'plaintext',
};

const replaceControlCharacters = (value: string, replacement = '') => {
    return Array.from(value || '').map((char) => (char.charCodeAt(0) < 32 ? replacement : char)).join('');
};

const normalizeFenceLanguage = (value: string | null | undefined) => {
    const normalizedValue = (value || '').trim().toLowerCase();
    if (!normalizedValue) return 'plaintext';

    const safeValue = normalizedValue.replace(/[^a-z0-9+#._-]/g, '').slice(0, 32);
    return safeValue || 'plaintext';
};

const normalizeFenceFilename = (value: string | null | undefined) => {
    return replaceControlCharacters(value || '', '_')
        .replace(/[\r\n\t]+/g, ' ')
        .replace(/[<>:"/\\|?*]/g, '_')
        .trim()
        .slice(0, 120);
};

const getPrismLanguage = (language: string) => {
    const normalizedLanguage = normalizeFenceLanguage(language);
    const prismLanguage = CODE_LANGUAGE_ALIASES[normalizedLanguage] || normalizedLanguage;
    return /^[a-z0-9_-]+$/.test(prismLanguage) ? prismLanguage : 'plaintext';
};

const highlightCodeContent = (codeContent: string, prismLanguage: string) => {
    const grammar = Prism.languages[prismLanguage];
    if (!grammar || prismLanguage === 'plaintext') {
        return escapeHtml(codeContent);
    }

    try {
        return Prism.highlight(codeContent, grammar, prismLanguage);
    } catch (error) {
        console.warn(`Prism failed to highlight ${prismLanguage}`, error);
        return escapeHtml(codeContent);
    }
};

const renderCodeLineNumberRows = (codeContent: string) => {
    const lineCount = Math.max(1, codeContent.split('\n').length);
    return `<span class="line-numbers-rows" aria-hidden="true">${'<span></span>'.repeat(lineCount)}</span>`;
};

const resizeCodeLineNumbers = (root: ParentNode) => {
    root.querySelectorAll('pre.line-numbers').forEach((pre) => {
        if (window.Prism?.plugins?.lineNumbers) {
            try {
                window.Prism.plugins.lineNumbers.resize(pre);
            } catch (error) {
                console.warn('Failed to resize line numbers:', error);
            }
        }
    });
};

type MarkdownUtils = {
    unescapeAll: (value: string) => string;
};

const parseFenceInfo = (info: string, markdownUtils: MarkdownUtils) => {
    const languageHint = info ? markdownUtils.unescapeAll(info).trim() : '';
    if (!languageHint) {
        return {
            actualLanguage: 'plaintext',
            prismLanguage: 'plaintext',
            filename: '',
        };
    }

    let rawLanguage = languageHint;
    let filename = '';

    if (languageHint.includes(':')) {
        const parts = languageHint.split(':', 2);
        rawLanguage = (parts[0] ?? '').trim();
        filename = normalizeFenceFilename(parts[1]);
    }

    const actualLanguage = normalizeFenceLanguage(rawLanguage);
    return {
        actualLanguage,
        prismLanguage: getPrismLanguage(actualLanguage),
        filename,
    };
};

const DOMPURIFY_SHARED_OPTIONS = {
    FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'foreignobject', 'link', 'meta', 'base'],
    FORBID_ATTR: ['srcdoc'],
};

const COLOR_TOKEN_PATTERN = /(^|[^\w#])(#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{4}|[0-9a-f]{3}))(?![0-9a-f])/gi;

const decorateColorTokens = (html: string) => {
    if (!html || typeof document === 'undefined') return html;

    const root = document.createElement('div');
    root.innerHTML = html;
    const walker = document.createTreeWalker(root, 4);
    const textNodes: Text[] = [];
    let currentNode = walker.nextNode();
    while (currentNode) {
        textNodes.push(currentNode as Text);
        currentNode = walker.nextNode();
    }

    textNodes.forEach((textNode) => {
        const parent = textNode.parentElement;
        if (!parent || parent.closest('pre, code, a, .chat-color-token')) return;

        COLOR_TOKEN_PATTERN.lastIndex = 0;
        const source = textNode.nodeValue || '';
        const fragment = document.createDocumentFragment();
        let cursor = 0;
        let match: RegExpExecArray | null;
        let found = false;

        while ((match = COLOR_TOKEN_PATTERN.exec(source)) !== null) {
            const boundary = match[1] || '';
            const token = match[2];
            if (!token) continue;
            const tokenStart = match.index + boundary.length;
            fragment.append(source.slice(cursor, tokenStart));

            const tokenWrapper = document.createElement('span');
            tokenWrapper.className = 'chat-color-token';
            const swatch = document.createElement('span');
            swatch.className = 'chat-color-swatch';
            swatch.setAttribute('aria-hidden', 'true');
            swatch.style.backgroundColor = token;
            const tokenLabel = document.createElement('span');
            tokenLabel.className = 'chat-color-value';
            tokenLabel.textContent = token;
            tokenWrapper.append(tokenLabel, swatch);
            fragment.append(tokenWrapper);

            cursor = tokenStart + token.length;
            found = true;
        }

        if (!found) return;
        fragment.append(source.slice(cursor));
        textNode.replaceWith(fragment);
    });

    return root.innerHTML;
};

type FormatLabels = {
    codeBlock: {
        codeSnippet: string;
        diagram: string;
        preview: string;
        code: string;
        download: string;
        copy: string;
        expand: string;
        collapse: string;
        tableCopy: string;
    };
    diagrams: {
        chartjsLoading: string;
        d3Loading: string;
        nomnomlLoading: string;
        mermaidLoading: string;
        svgLoading: string;
    };
    widgets: {
        creating: string;
    };
};

type FormatTextOptions = {
    labels?: Partial<{
        codeBlock: Partial<FormatLabels['codeBlock']>;
        diagrams: Partial<FormatLabels['diagrams']>;
        widgets: Partial<FormatLabels['widgets']>;
    }> | undefined;
};

type FormatUserMessageOptions = FormatTextOptions & {
    renderMarkdown?: boolean;
};

const DEFAULT_FORMAT_LABELS: FormatLabels = {
    codeBlock: {
        codeSnippet: 'Code snippet',
        diagram: 'Diagram',
        preview: 'Preview',
        code: 'Code',
        download: 'Download file',
        copy: 'Copy code',
        expand: 'Expand',
        collapse: 'Collapse',
        tableCopy: 'Copy table',
    },
    diagrams: {
        chartjsLoading: 'Loading chart...',
        d3Loading: 'Loading visualization...',
        nomnomlLoading: 'Loading diagram...',
        mermaidLoading: 'Loading diagram...',
        svgLoading: 'Rendering safe SVG...',
    },
    widgets: {
        creating: 'Creating {{tool}}',
    },
};

const resolveFormatLabels = (labels?: FormatTextOptions['labels']): FormatLabels => ({
    codeBlock: {
        ...DEFAULT_FORMAT_LABELS.codeBlock,
        ...(labels?.codeBlock || {}),
    },
    diagrams: {
        ...DEFAULT_FORMAT_LABELS.diagrams,
        ...(labels?.diagrams || {}),
    },
    widgets: {
        ...DEFAULT_FORMAT_LABELS.widgets,
        ...(labels?.widgets || {}),
    },
});

const interpolateLabel = (template: string, values: Record<string, string>) => (
    Object.entries(values).reduce(
        (current, [key, value]) => current.replace(new RegExp(`{{\\s*${key}\\s*}}`, 'g'), value),
        template
    )
);

const encodeBase64Utf8 = (value: string) => {
    try {
        const bytes = new TextEncoder().encode(value);
        let binary = '';
        bytes.forEach((byte) => {
            binary += String.fromCharCode(byte);
        });
        return btoa(binary);
    } catch (error) {
        console.warn('Base64 encoding failed:', error);
        return '';
    }
};

const buildVisualizationHost = (language: string, title: string, source: string) => {
    const encodedSource = encodeBase64Utf8(source);
    const mode = language.toLowerCase() === 'visualize-wide' ? 'wide' : 'normal';
    const safeTitle = escapeHtml(normalizeFenceFilename(title).slice(0, 120));
    return `<div class="visualize-instance-host" data-visualize-source-b64="${encodedSource}" data-visualize-title="${safeTitle}" data-visualize-mode="${mode}"></div>`;
};

const normalizeVisualizationFenceLine = (line: string) => {
    const normalized = line
        .trim()
        .replace(/\\`/g, '`')
        .replace(/｀/g, '`');
    return normalized.replace(/^((?:`[\t ]*){3,})/, (ticks) => ticks.replace(/[\t ]/g, ''));
};

const parseVisualizationFenceOpening = (line: string) => {
    const normalized = normalizeVisualizationFenceLine(line);
    const match = normalized.match(/^`{3,}[\t ]*(visualize(?:-wide)?)(?:[\t ]*:[\t ]*(.*))?$/i);
    if (!match) return null;
    return { language: match[1] || 'visualize', title: match[2] || '' };
};

const isFenceOnlyLine = (line: string) => /^`{3,}[\t ]*$/.test(
    normalizeVisualizationFenceLine(line)
);

const buildInteractivePlaceholder = (toolName: string, formatLabels: FormatLabels) => {
    const name = (toolName || '').toLowerCase();
    const label = escapeHtml(interpolateLabel(formatLabels.widgets.creating, { tool: name }));
    return `<span class="interactive-placeholder" data-tool="${name}" aria-live="polite"><span class="ip-spinner"></span><span class="ip-text">${label}</span></span>`;
};

const processVisualizationFences = (text: string, formatLabels: FormatLabels) => {
    const lines = text.replace(/\r\n?/g, '\n').split('\n');
    const output: string[] = [];

    for (let index = 0; index < lines.length; index += 1) {
        let opening = parseVisualizationFenceOpening(lines[index] || '');
        let contentStart = index + 1;

        if (!opening && isFenceOnlyLine(lines[index] || '')) {
            const detachedInfo = String(lines[index + 1] || '').trim().match(
                /^(visualize(?:-wide)?)(?:[\t ]*:[\t ]*(.*))?$/i
            );
            if (detachedInfo) {
                opening = {
                    language: detachedInfo[1] || 'visualize',
                    title: detachedInfo[2] || '',
                };
                contentStart = index + 2;
            }
        }

        if (!opening) {
            output.push(lines[index] || '');
            continue;
        }

        let closingIndex = -1;
        for (let candidate = contentStart; candidate < lines.length; candidate += 1) {
            if (isFenceOnlyLine(lines[candidate] || '')) {
                closingIndex = candidate;
                break;
            }
        }

        if (closingIndex === -1) {
            output.push(buildInteractivePlaceholder('visualize', formatLabels));
            break;
        }

        output.push(buildVisualizationHost(
            opening.language,
            opening.title,
            lines.slice(contentStart, closingIndex).join('\n')
        ));
        index = closingIndex;
    }

    return output.join('\n');
};

type DiagramBlockOptions = {
    language: string;
    filename: string;
    codeContent: string;
    labels?: FormatTextOptions['labels'];
};

type DiagramMeta = {
    label: string;
    blockClass: string;
    preview: string;
    codeLanguage?: string;
};

const buildDiagramBlock = ({ language, filename, codeContent, labels }: DiagramBlockOptions) => {
    const formatLabels = resolveFormatLabels(labels);
    const normalizedLanguage = language === 'd3' ? 'd3js' : (language === 'mmd' ? 'mermaid' : language);
    const diagramMeta: Record<string, DiagramMeta> = {
        chartjs: {
            label: 'Chart.js',
            blockClass: 'chartjs-block',
            preview: `
                <div class="diagram-pan-surface chart-container loading">
                    <canvas class="diagram-pan-target" role="img" aria-label="Chart.js diagram"></canvas>
                    <div class="chart-loading">${escapeHtml(formatLabels.diagrams.chartjsLoading)}</div>
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
                    <div class="d3-loading">${escapeHtml(formatLabels.diagrams.d3Loading)}</div>
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
                    <div class="nomnoml-loading">${escapeHtml(formatLabels.diagrams.nomnomlLoading)}</div>
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
                    <div class="mermaid-loading">${escapeHtml(formatLabels.diagrams.mermaidLoading)}</div>
                    <div class="mermaid-error" aria-live="polite"></div>
                </div>
            `,
            codeLanguage: 'mermaid'
        },
        svg: {
            label: 'SVG',
            blockClass: 'svg-block',
            preview: `
                <div class="svg-preview-surface svg-preview-container loading">
                    <div class="svg-preview-frame-host"></div>
                    <div class="svg-loading">${escapeHtml(formatLabels.diagrams.svgLoading)}</div>
                    <div class="svg-error" aria-live="polite"></div>
                </div>
            `,
            codeLanguage: 'markup'
        }
    };

    const meta = diagramMeta[normalizedLanguage];
    if (!meta) return null;

    const displayName = filename || meta.label;
    const safeName = escapeHtml(displayName);
    const safeSourceFilename = escapeHtml(filename || '');
    const codeLanguage = meta.codeLanguage || normalizedLanguage;
    const highlightedContent = highlightCodeContent(codeContent, codeLanguage);
    const previewMarkup = meta.preview;
    const safeDiagramLabel = escapeHtml(formatLabels.codeBlock.diagram);
    const safePreviewLabel = escapeHtml(formatLabels.codeBlock.preview);
    const safeCodeLabel = escapeHtml(formatLabels.codeBlock.code);
    const safeDownloadLabel = escapeHtml(formatLabels.codeBlock.download);
    const safeCopyLabel = escapeHtml(formatLabels.codeBlock.copy);
    const safeExpandLabel = escapeHtml(formatLabels.codeBlock.expand);
    const safeCollapseLabel = escapeHtml(formatLabels.codeBlock.collapse);

    return `
    <div class="code-block diagram-block ${meta.blockClass}" data-language="${normalizedLanguage}" data-filename="${safeName}" data-source-filename="${safeSourceFilename}">
        <div class="code-block-header">
            <span class="code-block-icon">&lt;/&gt;</span>
            <span class="code-block-filename">${safeName}</span>
            <div class="code-block-tabs" role="tablist" aria-label="${safeDiagramLabel}">
                <button class="code-tab-btn active" data-tab="preview" type="button" role="tab" aria-selected="true">${safePreviewLabel}</button>
                <button class="code-tab-btn" data-tab="code" type="button" role="tab" aria-selected="false" tabindex="-1">${safeCodeLabel}</button>
            </div>
            <div class="code-block-header-actions">
                <button class="download-code-btn" type="button" title="${safeDownloadLabel}" aria-label="${safeDownloadLabel}"><img src="/icons/ui/download.svg" alt="" aria-hidden="true"></button>
                <button class="copy-code-btn" type="button" title="${safeCopyLabel}" aria-label="${safeCopyLabel}"><img src="/icons/ui/copy.svg" alt="" aria-hidden="true"></button>
                <button class="toggle-code-btn" type="button" title="${safeExpandLabel}" aria-label="${safeExpandLabel}" aria-expanded="false" data-expand-label="${safeExpandLabel}" data-collapse-label="${safeCollapseLabel}">
                    <svg class="icon-expand" viewBox="0 0 24 24" fill="currentColor" width="18px" height="18px" style="display: block;" aria-hidden="true"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>
                    <svg class="icon-collapse" viewBox="0 0 24 24" fill="currentColor" width="18px" height="18px" style="display: none;" aria-hidden="true"><path d="M7.41 15.41L12 10.83l4.59 4.58L18 14l-6-6-6 6 1.41 1.41z"/></svg>
                </button>
            </div>
        </div>
        <div class="code-block-pane diagram-preview active" data-pane="preview" role="tabpanel">
            ${previewMarkup}
        </div>
        <div class="code-block-pane code-block-scroll-wrapper" data-pane="code" role="tabpanel" hidden>
            <div class="code-block-content">
                <pre class="line-numbers language-${codeLanguage}"><code class="language-${codeLanguage}">${highlightedContent}</code>${renderCodeLineNumberRows(codeContent)}</pre>
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
    const toRender = str.replace(/\\\[([\s\S]+?)\\\]/g, (_match, expr) => `$$${expr}$$`)
        .replace(/\\\(([^\n]+?)\\\)/g, (_match, expr) => `$${expr}$`);
    return renderLatexInHtml(originalRender(toRender, env));
};
md.renderer.rules.fence = (tokens, idx, _options, env) => {
    const token = tokens[idx];
    if (!token) return '';
    const formatLabels = resolveFormatLabels(env?.formatLabels);
    const codeContent = token.content;
    const { actualLanguage, prismLanguage, filename: parsedFilename } = parseFenceInfo(token.info, md.utils);
    let filename = parsedFilename;

    if (['beatbox', 'quiz', 'spinwheel'].includes(actualLanguage)) {
        const escapedState = escapeHtml(codeContent);
        return `<div class="${actualLanguage}-instance-host" data-${actualLanguage}-state='${escapedState}'></div>`;
    }

    if (actualLanguage === 'visualize' || actualLanguage === 'visualize-wide') {
        return buildVisualizationHost(actualLanguage, filename, codeContent);
    }

    const diagramBlock = buildDiagramBlock({
        language: actualLanguage,
        filename,
        codeContent,
        labels: formatLabels
    });
    if (diagramBlock) {
        return diagramBlock;
    }
    if (!filename) {
        filename = actualLanguage === 'plaintext' ? formatLabels.codeBlock.codeSnippet : (actualLanguage.charAt(0).toUpperCase() + actualLanguage.slice(1));
    }

    const safeFilename = escapeHtml(filename);
    const safeSourceFilename = escapeHtml(parsedFilename);
    const safeLanguage = escapeHtml(actualLanguage);
    const safePrismLanguage = escapeHtml(prismLanguage);
    const highlightedContent = highlightCodeContent(codeContent, prismLanguage);
    const safeDownloadLabel = escapeHtml(formatLabels.codeBlock.download);
    const safeCopyLabel = escapeHtml(formatLabels.codeBlock.copy);
    const safeExpandLabel = escapeHtml(formatLabels.codeBlock.expand);
    const safeCollapseLabel = escapeHtml(formatLabels.codeBlock.collapse);
    return `
    <div class="code-block" data-language="${safeLanguage}" data-filename="${safeFilename}" data-source-filename="${safeSourceFilename}">
        <div class="code-block-header">
            <span class="code-block-icon">&lt;/&gt;</span>
            <span class="code-block-filename">${safeFilename}</span>
            <div class="code-block-header-actions">
                <button class="download-code-btn" type="button" title="${safeDownloadLabel}" aria-label="${safeDownloadLabel}"><img src="/icons/ui/download.svg" alt="" aria-hidden="true"></button>
                <button class="copy-code-btn" type="button" title="${safeCopyLabel}" aria-label="${safeCopyLabel}"><img src="/icons/ui/copy.svg" alt="" aria-hidden="true"></button>
                <button class="toggle-code-btn" type="button" title="${safeExpandLabel}" aria-label="${safeExpandLabel}" aria-expanded="false" data-expand-label="${safeExpandLabel}" data-collapse-label="${safeCollapseLabel}">
                    <svg class="icon-expand" viewBox="0 0 24 24" fill="currentColor" width="18px" height="18px" style="display: block;" aria-hidden="true"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>
                    <svg class="icon-collapse" viewBox="0 0 24 24" fill="currentColor" width="18px" height="18px" style="display: none;" aria-hidden="true"><path d="M7.41 15.41L12 10.83l4.59 4.58L18 14l-6-6-6 6 1.41 1.41z"/></svg>
                </button>
            </div>
        </div>
        <div class="code-block-scroll-wrapper">
            <div class="code-block-content">
                <pre class="line-numbers language-${safePrismLanguage}"><code class="language-${safePrismLanguage}">${highlightedContent}</code>${renderCodeLineNumberRows(codeContent)}</pre>
            </div>
        </div>
    </div>`;
};
const processInteractiveHTMLTags = (text: string, labels?: FormatTextOptions['labels']) => {
    if (typeof text !== 'string' || !text) return text;
    const formatLabels = resolveFormatLabels(labels);
    text = processVisualizationFences(text, formatLabels);

    const unclosedConfigs = [
        { tag: 'beatbox' },
        { tag: 'quiz' },
        { tag: 'spinwheel' },
        { tag: 'visualize' }
    ];

    for (const cfg of unclosedConfigs) {
        const openTag = new RegExp(`<${cfg.tag}>`, 'i');
        const closeTag = new RegExp(`</${cfg.tag}>`, 'i');
        if (openTag.test(text) && !closeTag.test(text)) {
            const lastOpenIdx = text.toLowerCase().lastIndexOf(`<${cfg.tag}>`);
            if (lastOpenIdx !== -1) {
                const head = text.slice(0, lastOpenIdx);
                text = `${head}${buildInteractivePlaceholder(cfg.tag, formatLabels)}`;
            }
        }
    }

    const toBase64 = encodeBase64Utf8;

    text = text.replace(
        /<visualize(?:\s+title="([^"]{0,120})")?(?:\s+mode="(normal|wide)")?>([\s\S]*?)<\/visualize>/gi,
        (_match, title, mode, content) => {
            const encodedSource = toBase64(content.trim());
            return `<div class="visualize-instance-host" data-visualize-source-b64="${encodedSource}" data-visualize-title="${escapeHtml(title || '')}" data-visualize-mode="${mode === 'wide' ? 'wide' : 'normal'}"></div>`;
        }
    );

    text = text.replace(/<beatbox>([\s\S]*?)<\/beatbox>/gi, (_match, content) => {
        const encodedState = toBase64(content.trim());
        return `<div class="beatbox-instance-host" data-beatbox-state-b64='${encodedState}'></div>`;
    });

    text = text.replace(/<quiz>([\s\S]*?)<\/quiz>/gi, (_match, content) => {
        const encodedState = toBase64(content.trim());
        return `<div class="quiz-instance-host" data-quiz-state-b64='${encodedState}'></div>`;
    });

    text = text.replace(/<spinwheel>([\s\S]*?)<\/spinwheel>/gi, (_match, content) => {
        const encodedState = toBase64(content.trim());
        return `<div class="spinwheel-instance-host" data-spinwheel-state-b64='${encodedState}'></div>`;
    });
    text = text.replace(/<think(?:\s+data-open="(\d+)")?(?:\s+data-close="(\d+)")?>([\s\S]*?)<\/think>/gi, (_match, openTime, closeTime, content) => {
        const now = Date.now();
        const open = openTime ? parseInt(openTime, 10) : now;
        const close = closeTime ? parseInt(closeTime, 10) : now;
        const encodedContent = toBase64(content.trim());
        return `<div class="think-instance-host" data-think-open="${open}" data-think-close="${close}" data-think-content-b64="${encodedContent}"></div>`;
    });
    const unclosedThink = /<think(?:\s+data-open="(\d+)")?(?:\s+data-close="(\d+)?")?>/gi;
    if (unclosedThink.test(text)) {
        text = text.replace(unclosedThink, '');
    }

    return text;
};

export const formatText = (text: string, options: FormatTextOptions = {}) => {
    if (!text) return '';
    const formatLabels = resolveFormatLabels(options.labels);
    let processedText = processInteractiveHTMLTags(text, formatLabels);
    processedText = processedText.replace(/\\\[([\s\S]+?)\\\]/g, (_match, expr) => `$$${expr}$$`)
        .replace(/\\\(([^\n]+?)\\\)/g, (_match, expr) => `$${expr}$`);

    let renderedHtml = md.render(processedText, { formatLabels });
    renderedHtml = renderedHtml
        .replace(/<li>\[ \] /g, '<li class="task-list-item"><input type="checkbox" name="task_item" disabled> ')
        .replace(/<li>\[x\] /g, '<li class="task-list-item"><input type="checkbox" name="task_item" checked disabled> ');
    renderedHtml = renderedHtml.replace(/<table>/g, () => {
        const safeTableCopyLabel = escapeHtml(formatLabels.codeBlock.tableCopy);
        return `<div class="table-wrapper"><button class="table-copy-btn" type="button" title="${safeTableCopyLabel}" aria-label="${safeTableCopyLabel}"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg></button><div><table>`;
    });
    renderedHtml = renderedHtml.replace(/<\/table>/g, '</table></div></div>');
    renderedHtml = decorateColorTokens(renderedHtml);
    return DOMPurify.sanitize(renderedHtml, {
        ...DOMPURIFY_SHARED_OPTIONS,
        ADD_TAGS: ['svg', 'path', 'rect', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'div', 'span', 'mark', 'c', 'button', 'img', 'input', 'canvas'],
        ADD_ATTR: [
            'class', 'title', 'alt', 'viewBox', 'fill', 'width', 'height', 'd',
            'data-language', 'data-filename', 'data-source-filename', 'data-latex-source', 'data-latex-display', 'data-tab', 'data-pane', 'scope', 'colspan', 'rowspan',
            'type', 'checked', 'disabled', 'src', 'name',
            'data-beatbox-state', 'data-beatbox-state-b64', 'data-quiz-state', 'data-quiz-state-b64', 'data-spinwheel-state', 'data-spinwheel-state-b64',
            'data-visualize-source-b64', 'data-visualize-title', 'data-visualize-mode',
            'data-livebeatbox', 'data-livequiz', 'data-livespinwheel',
            'data-think-open', 'data-think-close', 'data-think-content', 'data-think-content-b64',
            'data-tool', 'data-source-ids', 's', 'tabindex', 'aria-live', 'aria-label', 'aria-hidden',
            'aria-expanded', 'aria-selected', 'aria-controls', 'role', 'stroke-width',
            'data-expand-label', 'data-collapse-label', 'hidden'
        ]
    });
};

export const formatPlainText = (text: string) => {
    if (!text) return '';
    return linkifyEscapedText(escapeHtml(text)).replace(/\n/g, '<br>');
};

const extractLeadingUserQuote = (text: string) => {
    const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
    if (!lines[0]?.trimStart().startsWith('>')) {
        return null;
    }

    const quoteLines: string[] = [];
    let index = 0;
    while (index < lines.length && lines[index]?.trimStart().startsWith('>')) {
        quoteLines.push((lines[index] ?? '').replace(/^\s*>\s?/, ''));
        index += 1;
    }

    while (index < lines.length && lines[index]?.trim() === '') {
        index += 1;
    }

    const quote = quoteLines.join('\n').trim();
    if (!quote) {
        return null;
    }

    return {
        quote,
        body: lines.slice(index).join('\n'),
    };
};

export const formatUserMessageText = (text: string, options: FormatUserMessageOptions = {}) => {
    if (!text) return '';

    const renderBody = (value: string) => (
        options.renderMarkdown
            ? formatUserText(value, { labels: options.labels })
            : formatPlainText(value)
    );
    const leadingQuote = extractLeadingUserQuote(text);

    if (!leadingQuote) {
        return renderBody(text);
    }

    const quoteHtml = `
        <div class="user-message-quote-display">
            <blockquote>${options.renderMarkdown
                ? formatUserText(leadingQuote.quote, { labels: options.labels })
                    .replace(/^<p>([\s\S]*)<\/p>\s*$/, '$1')
                : formatPlainText(leadingQuote.quote)}</blockquote>
        </div>
    `;
    const bodyHtml = leadingQuote.body.trim() ? renderBody(leadingQuote.body) : '';
    return `${quoteHtml}${bodyHtml}`;
};

const userMd = new MarkdownIt({
    html: false,
    linkify: true,
    typographer: true,
});
const originalUserRender = userMd.render.bind(userMd);
userMd.render = function (str, env) {
    const toRender = str.replace(/\\\[([\s\S]+?)\\\]/g, (_match, expr) => `$$${expr}$$`)
        .replace(/\\\(([^\n]+?)\\\)/g, (_match, expr) => `$${expr}$`);
    return renderLatexInHtml(originalUserRender(toRender, env));
};

userMd.renderer.rules.fence = (tokens, idx, _options, env) => {
    const token = tokens[idx];
    if (!token) return '';
    const formatLabels = resolveFormatLabels(env?.formatLabels);
    const codeContent = token.content || '';
    const { actualLanguage, prismLanguage, filename: parsedFilename } = parseFenceInfo(token.info, userMd.utils);
    let filename = parsedFilename;

    const diagramBlock = buildDiagramBlock({
        language: actualLanguage,
        filename,
        codeContent,
        labels: formatLabels
    });
    if (diagramBlock) {
        return diagramBlock;
    }

    if (!filename) {
        filename = actualLanguage === 'plaintext' ? formatLabels.codeBlock.codeSnippet : (actualLanguage.charAt(0).toUpperCase() + actualLanguage.slice(1));
    }

    const safeFilename = escapeHtml(filename);
    const safeSourceFilename = escapeHtml(parsedFilename);
    const safeLanguage = escapeHtml(actualLanguage);
    const safePrismLanguage = escapeHtml(prismLanguage);
    const highlightedContent = highlightCodeContent(codeContent, prismLanguage);
    const safeDownloadLabel = escapeHtml(formatLabels.codeBlock.download);
    const safeCopyLabel = escapeHtml(formatLabels.codeBlock.copy);
    const safeExpandLabel = escapeHtml(formatLabels.codeBlock.expand);
    const safeCollapseLabel = escapeHtml(formatLabels.codeBlock.collapse);

    return `
    <div class="code-block" data-language="${safeLanguage}" data-filename="${safeFilename}" data-source-filename="${safeSourceFilename}">
        <div class="code-block-header">
            <span class="code-block-icon">&lt;/&gt;</span>
            <span class="code-block-filename">${safeFilename}</span>
            <div class="code-block-header-actions">
                <button class="download-code-btn" type="button" title="${safeDownloadLabel}" aria-label="${safeDownloadLabel}"><img src="/icons/ui/download.svg" alt="" aria-hidden="true"></button>
                <button class="copy-code-btn" type="button" title="${safeCopyLabel}" aria-label="${safeCopyLabel}"><img src="/icons/ui/copy.svg" alt="" aria-hidden="true"></button>
                <button class="toggle-code-btn" type="button" title="${safeExpandLabel}" aria-label="${safeExpandLabel}" aria-expanded="false" data-expand-label="${safeExpandLabel}" data-collapse-label="${safeCollapseLabel}">
                    <svg class="icon-expand" viewBox="0 0 24 24" fill="currentColor" width="18px" height="18px" style="display: block;" aria-hidden="true"><path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6 1.41-1.41z"/></svg>
                    <svg class="icon-collapse" viewBox="0 0 24 24" fill="currentColor" width="18px" height="18px" style="display: none;" aria-hidden="true"><path d="M7.41 15.41L12 10.83l4.59 4.58L18 14l-6-6-6 6 1.41 1.41z"/></svg>
                </button>
            </div>
        </div>
        <div class="code-block-scroll-wrapper">
            <div class="code-block-content">
                <pre class="line-numbers language-${safePrismLanguage}"><code class="language-${safePrismLanguage}">${highlightedContent}</code>${renderCodeLineNumberRows(codeContent)}</pre>
            </div>
        </div>
    </div>`;
};

export const formatUserText = (text: string, options: FormatTextOptions = {}) => {
    if (!text) return '';
    const formatLabels = resolveFormatLabels(options.labels);
    const renderedHtml = userMd.render(text, { formatLabels });
    return DOMPurify.sanitize(renderedHtml, {
        ...DOMPURIFY_SHARED_OPTIONS,
        ADD_TAGS: ['svg', 'path', 'rect', 'div', 'span', 'button', 'img', 'input', 'pre', 'code', 'canvas'],
        ADD_ATTR: [
            'class', 'title', 'alt', 'viewBox', 'fill', 'width', 'height', 'd',
            'type', 'checked', 'disabled', 'src', 'name',
            'data-language', 'data-filename', 'data-source-filename', 'data-latex-source', 'data-latex-display', 'data-tab', 'data-pane',
            'aria-label', 'aria-hidden', 'aria-expanded', 'aria-selected', 'aria-controls',
            'role', 'aria-live', 'tabindex', 'data-expand-label', 'data-collapse-label', 'hidden',
        ]
    });
};

export const highlightCode = (container?: ParentNode) => {
    const root = container || document;
    root.querySelectorAll('pre.line-numbers > .line-numbers-rows').forEach((rows) => rows.remove());
    root.querySelectorAll('code[class*="language-"]').forEach((code) => {
        code.removeAttribute('data-highlighted');
    });

    if (container) {
        Prism.highlightAllUnder(container);
        resizeCodeLineNumbers(container);
        return;
    }

    Prism.highlightAll();
    resizeCodeLineNumbers(document);
};

export const refreshCodeLineNumbers = (container?: ParentNode) => {
    const root = container || document;
    const codeBlocks = Array.from(root.querySelectorAll('pre.line-numbers'));
    if (codeBlocks.length === 0) return;

    const hasMissingRows = codeBlocks.some((pre) => !pre.querySelector('.line-numbers-rows'));
    if (hasMissingRows) {
        highlightCode(root);
        return;
    }

    resizeCodeLineNumbers(root);
};
