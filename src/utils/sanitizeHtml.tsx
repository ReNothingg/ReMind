import DOMPurify from 'dompurify';

const ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'u', 'code', 'pre', 'ul', 'ol', 'li',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'a', 'hr',
    'table', 'thead', 'tbody', 'tr', 'td', 'th', 'div', 'span',
    'img', 'b', 'i', 'del', 'ins', 'sup', 'sub'
];

const ALLOWED_ATTR = [
    'href', 'title',
    'src', 'alt', 'width', 'height',
    'class', 'id',
    'colspan', 'rowspan'
];

const DEFAULT_CONFIG = {
    ALLOWED_TAGS: ALLOWED_TAGS,
    ALLOWED_ATTR: ALLOWED_ATTR,
    ALLOW_DATA_ATTR: true,
    ALLOW_ARIA_ATTR: true,
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed'],
    FORBID_ATTR: ['style'],
    ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|blob):|(?:data:image\/)|[./#])/i,
};


export function sanitizeHtml(html, options = {}) {
    if (!html || typeof html !== 'string') {
        return '';
    }

    const config = { ...DEFAULT_CONFIG, ...(options || {}) };
    return DOMPurify.sanitize(html, config);
}


export function SafeHtmlRenderer({ html, className = '', ...props }) {
    const sanitized = sanitizeHtml(html);

    return (
        <div
            className={className}
            dangerouslySetInnerHTML={{ __html: sanitized }}
            {...props}
        />
    );
}

export default sanitizeHtml;
