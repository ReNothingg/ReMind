const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';
const XLINK_NAMESPACE = 'http://www.w3.org/1999/xlink';
const MAX_SVG_MARKUP_LENGTH = 200_000;
const MAX_SVG_NODE_COUNT = 5_000;

const SAFE_SVG_TAGS = new Set([
    'svg',
    'g',
    'path',
    'rect',
    'circle',
    'ellipse',
    'line',
    'polyline',
    'polygon',
    'text',
    'tspan',
    'defs',
    'title',
    'desc',
    'lineargradient',
    'radialgradient',
    'stop',
    'clippath',
    'mask',
    'filter',
    'fedropshadow',
    'fegaussianblur',
    'feoffset',
    'feblend',
    'fecolormatrix',
    'fecomposite',
    'feflood',
    'femerge',
    'femergenode',
]);

const SAFE_SVG_ATTRIBUTES = new Set([
    'xmlns',
    'xmlns:xlink',
    'version',
    'viewbox',
    'width',
    'height',
    'x',
    'y',
    'x1',
    'y1',
    'x2',
    'y2',
    'cx',
    'cy',
    'r',
    'rx',
    'ry',
    'd',
    'points',
    'transform',
    'opacity',
    'fill',
    'fill-opacity',
    'fill-rule',
    'stroke',
    'stroke-width',
    'stroke-linecap',
    'stroke-linejoin',
    'stroke-miterlimit',
    'stroke-dasharray',
    'stroke-dashoffset',
    'stroke-opacity',
    'preserveaspectratio',
    'vector-effect',
    'shape-rendering',
    'id',
    'role',
    'aria-label',
    'focusable',
    'font-family',
    'font-size',
    'font-style',
    'font-weight',
    'text-anchor',
    'dominant-baseline',
    'textlength',
    'lengthadjust',
    'letter-spacing',
    'word-spacing',
    'paint-order',
    'gradientunits',
    'gradienttransform',
    'spreadmethod',
    'offset',
    'stop-color',
    'stop-opacity',
    'clippathunits',
    'clip-path',
    'clip-rule',
    'mask',
    'maskunits',
    'maskcontentunits',
    'filter',
    'filterunits',
    'primitiveunits',
    'stddeviation',
    'dx',
    'dy',
    'in',
    'in2',
    'result',
    'values',
    'type',
    'mode',
    'operator',
    'k1',
    'k2',
    'k3',
    'k4',
    'flood-color',
    'flood-opacity',
    'color-interpolation-filters',
    'xml:space',
    'style',
    'href',
    'xlink:href',
]);

const URL_REFERENCE_ATTRIBUTES = new Set(['href', 'xlink:href']);
const URL_CAPABLE_ATTRIBUTES = new Set(['fill', 'stroke', 'clip-path', 'mask', 'filter']);
const SAFE_STYLE_PROPERTIES = new Set([
    'fill',
    'fill-opacity',
    'fill-rule',
    'stroke',
    'stroke-width',
    'stroke-linecap',
    'stroke-linejoin',
    'stroke-miterlimit',
    'stroke-dasharray',
    'stroke-dashoffset',
    'stroke-opacity',
    'opacity',
    'font-family',
    'font-size',
    'font-style',
    'font-weight',
    'text-anchor',
    'dominant-baseline',
    'letter-spacing',
    'word-spacing',
    'paint-order',
    'stop-color',
    'stop-opacity',
    'color',
    'filter',
    'clip-path',
    'mask',
]);

const UNSAFE_TOKEN_PATTERN = /(?:javascript:|vbscript:|data:|@import|expression\s*\()/i;
const SAFE_ID_PATTERN = /^[A-Za-z_][\w:.-]*$/;
const SAFE_FRAGMENT_REFERENCE_PATTERN = /^#([A-Za-z_][\w:.-]*)$/;
const SAFE_INTERNAL_URL_PATTERN = /^url\(\s*#([A-Za-z_][\w:.-]*)\s*\)$/i;

export interface SanitizedSvgResult {
    sanitizedMarkup: string | null;
    error?: string;
}

const escapeHtml = (value: string) => {
    return value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
};

const hasControlCharacters = (value: string) => {
    return Array.from(value).some((char) => {
        const code = char.charCodeAt(0);
        return (code >= 0 && code < 32) || code === 127;
    });
};

const normalizePreviewBackground = (value?: string) => {
    const trimmedValue = (value || '').trim();
    if (!trimmedValue) return 'transparent';

    // Keep the CSS injection surface narrow even though the source is computed browser CSS.
    if (!/^[#(),.%\sA-Za-z0-9\-\/]+$/.test(trimmedValue)) {
        return 'transparent';
    }

    return trimmedValue;
};

const sanitizeUrlCapableValue = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return null;
    if (SAFE_INTERNAL_URL_PATTERN.test(trimmed)) return trimmed;
    if (trimmed.includes('url(')) return null;
    if (UNSAFE_TOKEN_PATTERN.test(trimmed)) return null;
    return trimmed;
};

const sanitizeStyleAttribute = (styleValue: string) => {
    const sanitizedDeclarations = styleValue
        .split(';')
        .map((entry) => entry.trim())
        .filter(Boolean)
        .map((entry) => {
            const separatorIndex = entry.indexOf(':');
            if (separatorIndex === -1) return null;

            const property = entry.slice(0, separatorIndex).trim().toLowerCase();
            const value = entry.slice(separatorIndex + 1).trim();
            if (!property || !value || !SAFE_STYLE_PROPERTIES.has(property)) return null;
            if (hasControlCharacters(value) || value.includes('<') || value.includes('>')) {
                return null;
            }

            const sanitizedValue = URL_CAPABLE_ATTRIBUTES.has(property)
                ? sanitizeUrlCapableValue(value)
                : (UNSAFE_TOKEN_PATTERN.test(value) ? null : value);

            if (!sanitizedValue) return null;
            return `${property}: ${sanitizedValue}`;
        })
        .filter((entry): entry is string => Boolean(entry));

    return sanitizedDeclarations.length ? sanitizedDeclarations.join('; ') : null;
};

const sanitizeSvgAttribute = (attributeName: string, attributeValue: string) => {
    const normalizedName = attributeName.toLowerCase();
    const trimmedValue = attributeValue.trim();

    if (!trimmedValue) return null;
    if (normalizedName.startsWith('on')) return null;
    if (hasControlCharacters(trimmedValue)) return null;
    if (trimmedValue.includes('<') || trimmedValue.includes('>')) return null;

    if (normalizedName === 'style') {
        return sanitizeStyleAttribute(trimmedValue);
    }

    if (normalizedName === 'id') {
        return SAFE_ID_PATTERN.test(trimmedValue) ? trimmedValue : null;
    }

    if (normalizedName === 'xmlns') {
        return trimmedValue === SVG_NAMESPACE ? trimmedValue : null;
    }

    if (normalizedName === 'xmlns:xlink') {
        return trimmedValue === XLINK_NAMESPACE ? trimmedValue : null;
    }

    if (URL_REFERENCE_ATTRIBUTES.has(normalizedName)) {
        return SAFE_FRAGMENT_REFERENCE_PATTERN.test(trimmedValue) ? trimmedValue : null;
    }

    if (URL_CAPABLE_ATTRIBUTES.has(normalizedName)) {
        return sanitizeUrlCapableValue(trimmedValue);
    }

    if (UNSAFE_TOKEN_PATTERN.test(trimmedValue)) return null;

    return trimmedValue;
};

const cloneSafeSvgNode = (
    sourceNode: Node,
    targetDocument: XMLDocument,
    state: { nodeCount: number }
): Node | null => {
    if (state.nodeCount >= MAX_SVG_NODE_COUNT) {
        throw new Error('SVG is too complex');
    }

    if (sourceNode.nodeType === Node.TEXT_NODE) {
        return targetDocument.createTextNode(sourceNode.textContent || '');
    }

    if (sourceNode.nodeType !== Node.ELEMENT_NODE) {
        return null;
    }

    const sourceElement = sourceNode as Element;
    const tagName = sourceElement.tagName.toLowerCase();
    const namespace = sourceElement.namespaceURI;

    if (!SAFE_SVG_TAGS.has(tagName)) return null;
    if (namespace && namespace !== SVG_NAMESPACE) return null;

    state.nodeCount += 1;

    const safeElement = targetDocument.createElementNS(SVG_NAMESPACE, sourceElement.tagName);
    for (const attribute of Array.from(sourceElement.attributes)) {
        const normalizedName = attribute.name.toLowerCase();
        if (!SAFE_SVG_ATTRIBUTES.has(normalizedName)) continue;

        const sanitizedValue = sanitizeSvgAttribute(normalizedName, attribute.value);
        if (!sanitizedValue) continue;

        if (normalizedName === 'xlink:href') {
            safeElement.setAttributeNS(XLINK_NAMESPACE, 'xlink:href', sanitizedValue);
            continue;
        }

        safeElement.setAttribute(attribute.name, sanitizedValue);
    }

    for (const childNode of Array.from(sourceElement.childNodes)) {
        const safeChild = cloneSafeSvgNode(childNode, targetDocument, state);
        if (safeChild) {
            safeElement.appendChild(safeChild);
        }
    }

    return safeElement;
};

const ensureResponsiveViewBox = (svgElement: Element) => {
    if (svgElement.hasAttribute('viewBox')) return;

    const width = Number.parseFloat((svgElement.getAttribute('width') || '').replace('px', ''));
    const height = Number.parseFloat((svgElement.getAttribute('height') || '').replace('px', ''));

    if (Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0) {
        svgElement.setAttribute('viewBox', `0 0 ${width} ${height}`);
    }
};

export const sanitizeSvgMarkup = (markup: string): SanitizedSvgResult => {
    if (typeof markup !== 'string') {
        return { sanitizedMarkup: null, error: 'SVG source is missing' };
    }

    const trimmedMarkup = markup.trim();
    if (!trimmedMarkup) {
        return { sanitizedMarkup: null, error: 'SVG source is empty' };
    }

    if (trimmedMarkup.length > MAX_SVG_MARKUP_LENGTH) {
        return { sanitizedMarkup: null, error: 'SVG source is too large' };
    }

    const parser = new DOMParser();
    const parsedDocument = parser.parseFromString(trimmedMarkup, 'image/svg+xml');
    if (parsedDocument.querySelector('parsererror')) {
        return { sanitizedMarkup: null, error: 'SVG markup is invalid XML' };
    }

    const sourceRoot = parsedDocument.documentElement;
    if (!sourceRoot || sourceRoot.tagName.toLowerCase() !== 'svg') {
        return { sanitizedMarkup: null, error: 'SVG root element is required' };
    }

    const safeDocument = document.implementation.createDocument(SVG_NAMESPACE, 'svg', null);
    const clonedRoot = cloneSafeSvgNode(sourceRoot, safeDocument, { nodeCount: 0 });
    if (!(clonedRoot instanceof Element) || clonedRoot.tagName.toLowerCase() !== 'svg') {
        return { sanitizedMarkup: null, error: 'SVG content was blocked by the sanitizer' };
    }

    clonedRoot.setAttribute('xmlns:xlink', XLINK_NAMESPACE);
    clonedRoot.setAttribute('role', clonedRoot.getAttribute('role') || 'img');
    clonedRoot.setAttribute('focusable', 'false');
    ensureResponsiveViewBox(clonedRoot);

    safeDocument.replaceChild(clonedRoot, safeDocument.documentElement);

    return {
        sanitizedMarkup: new XMLSerializer().serializeToString(clonedRoot),
    };
};

export const buildSvgPreviewDocument = (
    sanitizedMarkup: string,
    title = 'SVG preview',
    backgroundColor?: string
) => {
    const safeBackgroundColor = normalizePreviewBackground(backgroundColor);
    return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; child-src 'none'; connect-src 'none'; img-src 'none'; media-src 'none'; object-src 'none'; style-src 'unsafe-inline'">
<title>${escapeHtml(title)}</title>
<style>
html, body {
  margin: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: ${safeBackgroundColor};
}

body {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px;
  box-sizing: border-box;
}

svg {
  display: block;
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: auto;
}
</style>
</head>
<body>
${sanitizedMarkup}
</body>
</html>`;
};
