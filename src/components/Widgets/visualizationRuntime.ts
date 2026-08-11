import katex from 'katex';
import katexCss from 'katex/dist/katex.min.css?raw';

export const MAX_VISUALIZATION_SOURCE_BYTES = 768 * 1024;

export type VisualizationAppearance = {
    theme: 'light' | 'dark';
    locale: string;
    direction: 'ltr' | 'rtl';
    accentColor: string;
    compactMode: boolean;
    highContrast: boolean;
    reducedMotion: boolean;
    fontFamily: string;
    fontSize: string;
};

export type VisualizationContext = {
    appearance: VisualizationAppearance;
    tokens: Record<string, string>;
};

const TOKEN_SOURCES: Record<string, string> = {
    '--background': '--color-bg-main',
    '--foreground': '--color-text-primary',
    '--card': '--color-bg-surface',
    '--card-foreground': '--color-text-primary',
    '--popover': '--color-bg-surface',
    '--popover-foreground': '--color-text-primary',
    '--primary': '--color-accent',
    '--primary-foreground': '--color-text-on-accent-bg',
    '--secondary': '--color-bg-interactive',
    '--secondary-foreground': '--color-text-primary',
    '--muted': '--color-bg-surface-alt',
    '--muted-foreground': '--color-text-secondary',
    '--accent': '--color-bg-interactive',
    '--accent-foreground': '--color-text-primary',
    '--destructive': '--color-error',
    '--border': '--color-border-medium',
    '--input': '--input-element-border',
    '--ring': '--color-border-focus',
    '--blue': '--color-accent',
    '--orange': '--color-warning',
    '--green': '--color-success',
    '--red': '--color-error',
    '--purple': '--color-accent',
    '--yellow': '--color-warning',
    '--viz-series-1': '--color-accent',
    '--viz-series-2': '--color-success',
    '--viz-series-3': '--color-warning',
    '--viz-series-4': '--color-error',
    '--viz-series-5': '--color-text-secondary',
    '--viz-series-6': '--color-border-strong',
    '--font-family': '--font-family-main',
    '--font-size-base': '--type-body',
    '--radius-sm': '--radius-sm',
    '--radius-md': '--radius-md',
    '--radius-lg': '--radius-lg',
};

const SAFE_CSS_VALUE = /^[^<>{}\r\n]+$/;

const safeCssValue = (value: string, fallback: string) => {
    const normalized = String(value || '').trim();
    return normalized && SAFE_CSS_VALUE.test(normalized) ? normalized : fallback;
};

export const readVisualizationContext = (
    settings: Record<string, unknown> = {},
): VisualizationContext => {
    const root = document.documentElement;
    const computed = window.getComputedStyle(root);
    const tokens = Object.fromEntries(Object.entries(TOKEN_SOURCES).map(([target, source]) => {
        const fallback = target.includes('foreground') ? '#111827' : 'transparent';
        return [target, safeCssValue(computed.getPropertyValue(source), fallback)];
    }));
    const resolvedTheme = root.dataset.theme === 'dark' ? 'dark' : 'light';
    const locale = String(settings.interface_language || root.lang || 'en').slice(0, 16);
    const direction = root.dir === 'rtl' || locale === 'ar' ? 'rtl' : 'ltr';

    return {
        appearance: {
            theme: resolvedTheme,
            locale,
            direction,
            accentColor: String(settings.accentColor || root.dataset.accentColor || ''),
            compactMode: settings.compactMode === true,
            highContrast: settings.highContrast === true,
            reducedMotion: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true,
            fontFamily: safeCssValue(computed.getPropertyValue('--font-family-main'), 'system-ui, sans-serif'),
            fontSize: safeCssValue(computed.getPropertyValue('--type-body'), '16px'),
        },
        tokens,
    };
};

const escapeHtmlAttribute = (value: string) => value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

const serializeForInlineScript = (value: unknown) => JSON.stringify(value)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');

const MATH_DELIMITER_RE = /\\\[([\s\S]+?)\\\]|\$\$([\s\S]+?)\$\$|\\\(([^\n]+?)\\\)|(?<!\\)\$([^$\n]+?)\$/g;
const KATEX_RUNTIME_CSS = katexCss.replace(
    /url\((['"]?)fonts\//g,
    'url($1https://cdn.jsdelivr.net/npm/katex@0.16.25/dist/fonts/',
);
const MATH_SKIP_SELECTOR = 'script, style, textarea, pre, code, svg, [data-no-math]';

const renderMathTextNode = (documentRef: Document, node: Text) => {
    const source = node.nodeValue || '';
    MATH_DELIMITER_RE.lastIndex = 0;
    if (!MATH_DELIMITER_RE.test(source)) return;
    MATH_DELIMITER_RE.lastIndex = 0;

    const fragment = documentRef.createDocumentFragment();
    let cursor = 0;
    let match: RegExpExecArray | null = MATH_DELIMITER_RE.exec(source);
    while (match) {
        if (match.index > cursor) {
            fragment.appendChild(documentRef.createTextNode(source.slice(cursor, match.index)));
        }
        const expression = String(match[1] || match[2] || match[3] || match[4] || '').trim();
        const displayMode = Boolean(match[1] || match[2]);
        const wrapper = documentRef.createElement(displayMode ? 'div' : 'span');
        wrapper.className = 'remind-visualization-math';
        wrapper.dataset.latexSource = expression;
        wrapper.dataset.latexDisplay = String(displayMode);
        wrapper.innerHTML = katex.renderToString(expression, {
            displayMode,
            throwOnError: false,
            strict: false,
            trust: false,
        });
        fragment.appendChild(wrapper);
        cursor = match.index + match[0].length;
        match = MATH_DELIMITER_RE.exec(source);
    }
    if (cursor < source.length) {
        fragment.appendChild(documentRef.createTextNode(source.slice(cursor)));
    }
    node.replaceWith(fragment);
};

export const renderMathInVisualizationFragment = (fragment: string) => {
    if (!fragment || typeof DOMParser === 'undefined') return fragment;
    const parsed = new DOMParser().parseFromString(`<body>${fragment}</body>`, 'text/html');
    const nodes: Text[] = [];
    const walker = parsed.createTreeWalker(parsed.body, NodeFilter.SHOW_TEXT);
    let current = walker.nextNode();
    while (current) {
        if (
            current instanceof Text
            && !current.parentElement?.closest(MATH_SKIP_SELECTOR)
        ) {
            nodes.push(current);
        }
        current = walker.nextNode();
    }
    nodes.forEach((node) => renderMathTextNode(parsed, node));
    return parsed.body.innerHTML;
};

const VISUALIZATION_BASE_CSS = String.raw`
* { box-sizing: border-box; }
html { color-scheme: light dark; background: transparent; }
body {
    margin: 0;
    overflow-x: hidden;
    background: transparent;
    color: var(--foreground);
    font-family: var(--font-family);
    font-size: var(--font-size-base);
    line-height: 1.5;
}
button, input, select, textarea { font: inherit; color: inherit; }
button, input, select, textarea, a { accent-color: var(--primary); }
a { color: var(--primary); }
h1, h2, h3, p { margin-block-start: 0; }
h1, h2, h3 { font-weight: 500; }
svg, canvas, img { max-width: 100%; }
.card {
    padding: 16px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--card);
    color: var(--card-foreground);
}
.viz-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(180px, 100%), 1fr)); gap: 12px; }
.viz-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.viz-controls { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; margin-block: 12px; }
.d-flex { display: flex; }
.justify-content-between { justify-content: space-between; }
.align-items-center { align-items: center; }
.p-3 { padding: 16px; }
.mb-3 { margin-bottom: 16px; }
.m-0 { margin: 0; }
.h5 { font-size: 1.1em; font-weight: 500; }
.viz-stat-value { font-size: 1.5em; font-weight: 500; font-variant-numeric: tabular-nums; }
.viz-badge { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 999px; background: var(--accent); color: var(--accent-foreground); }
.btn {
    min-height: 36px;
    padding: 7px 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--secondary);
    color: var(--secondary-foreground);
    cursor: pointer;
}
.btn-primary { border-color: var(--primary); background: var(--primary); color: var(--primary-foreground); }
.btn-ghost { border-color: transparent; background: transparent; }
.btn-block { width: 100%; }
.btn:disabled { cursor: not-allowed; opacity: .55; }
.form-label { display: grid; gap: 6px; min-width: min(220px, 100%); }
.form-control, .form-select {
    width: 100%;
    min-height: 38px;
    padding: 7px 10px;
    border: 1px solid var(--input);
    border-radius: var(--radius-sm);
    background: var(--card);
    color: var(--card-foreground);
}
.form-range { width: 100%; }
.form-check { display: inline-flex; align-items: center; gap: 8px; }
.table-responsive { max-width: 100%; overflow-x: auto; }
.table { width: 100%; border-collapse: collapse; }
.table th, .table td { padding: 9px 10px; border-bottom: 1px solid var(--border); text-align: start; }
.table-sm th, .table-sm td { padding: 6px 8px; }
.text-small { font-size: .82em; }
.text-muted { color: var(--muted-foreground); }
.text-destructive { color: var(--destructive); }
.text-end { text-align: end !important; font-variant-numeric: tabular-nums; }
.text-center { text-align: center !important; }
.text-nowrap { white-space: nowrap; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
@media (max-width: 480px) {
    .card { padding: 12px; }
    .viz-controls { align-items: stretch; }
    .viz-controls > * { min-width: 100%; }
}
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { scroll-behavior: auto !important; animation-duration: .001ms !important; animation-iteration-count: 1 !important; transition-duration: .001ms !important; }
}`;

type BuildVisualizationDocumentOptions = {
    fragment: string;
    context: VisualizationContext;
    channelId: string;
};

export const buildVisualizationDocument = ({
    fragment,
    context,
    channelId,
}: BuildVisualizationDocumentOptions) => {
    const tokenDeclarations = Object.entries(context.tokens)
        .map(([name, value]) => `${name}:${safeCssValue(value, 'transparent')}`)
        .join(';');
    const runtimeContext = {
        ...context,
        capabilities: {
            localInteraction: true,
            followUpMessage: true,
            networkRequests: false,
            persistentStorage: false,
        },
    };
    const serializedContext = serializeForInlineScript(runtimeContext);
    const serializedChannel = serializeForInlineScript(channelId);
    const lang = escapeHtmlAttribute(context.appearance.locale);
    const direction = context.appearance.direction;
    const csp = [
        "default-src 'none'",
        "script-src 'unsafe-inline' https://cdnjs.cloudflare.com https://esm.sh https://cdn.jsdelivr.net https://unpkg.com",
        "style-src 'unsafe-inline' https://fonts.googleapis.com https://fonts.bunny.net",
        "font-src data: https://fonts.gstatic.com https://fonts.bunny.net https://cdn.jsdelivr.net",
        "img-src data: blob:",
        "media-src data: blob:",
        "connect-src 'none'",
        "frame-src 'none'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    ].join('; ');

    const fragmentWithMath = renderMathInVisualizationFragment(fragment);

    return `<!doctype html>
<html lang="${lang}" dir="${direction}" data-theme="${context.appearance.theme}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="${escapeHtmlAttribute(csp)}">
<style>:root{${tokenDeclarations};--font-family:${safeCssValue(context.appearance.fontFamily, 'system-ui, sans-serif')};--font-size-base:${safeCssValue(context.appearance.fontSize, '16px')}}${KATEX_RUNTIME_CSS}${VISUALIZATION_BASE_CSS}</style>
<script>
(() => {
  const context = ${serializedContext};
  const channelId = ${serializedChannel};
  const send = (type, payload = {}) => window.parent.postMessage({ type, channelId, ...payload }, '*');
  const followUp = async (request) => {
    const prompt = typeof request === 'string' ? request : request?.prompt;
    const title = typeof request === 'object' && request ? request.title : '';
    if (typeof prompt !== 'string' || !prompt.trim()) throw new TypeError();
    send('remind:visualization:follow-up', { prompt: prompt.trim().slice(0, 4000), title: String(title || '').trim().slice(0, 250) });
    return { queued: true };
  };
  let mathRequestSequence = 0;
  const pendingMath = new Map();
  const renderMath = (expression, options = {}) => new Promise((resolve) => {
    const requestId = String(++mathRequestSequence);
    pendingMath.set(requestId, resolve);
    send('remind:visualization:math-request', {
      requestId,
      expression: String(expression || '').slice(0, 4000),
      displayMode: options.displayMode === true,
    });
  });
  const renderMathElement = async (element, expression, options = {}) => {
    if (!(element instanceof Element)) throw new TypeError();
    element.innerHTML = await renderMath(expression, options);
    return element;
  };
  addEventListener('message', (event) => {
    if (event.source !== window.parent || event.data?.type !== 'remind:visualization:math-result' || event.data?.channelId !== channelId) return;
    const resolve = pendingMath.get(String(event.data.requestId || ''));
    if (!resolve) return;
    pendingMath.delete(String(event.data.requestId || ''));
    resolve(String(event.data.html || ''));
  });
  const bridge = Object.freeze({ ...context, sendFollowUpMessage: followUp, renderMath, renderMathElement });
  Object.defineProperty(window, 'remind', { value: bridge, configurable: false, writable: false });
  Object.defineProperty(window, 'openai', { value: bridge, configurable: false, writable: false });
  const publishHeight = () => {
    const height = Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0);
    send('remind:visualization:resize', { height: Math.ceil(height) });
  };
  addEventListener('DOMContentLoaded', () => {
    publishHeight();
    new ResizeObserver(publishHeight).observe(document.documentElement);
    new MutationObserver(publishHeight).observe(document.body, { childList: true, subtree: true, attributes: true });
  });
  addEventListener('load', publishHeight);
})();
</script>
</head>
<body>${fragmentWithMath}</body>
</html>`;
};
