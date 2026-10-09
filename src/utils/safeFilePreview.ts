import DOMPurify from 'dompurify';

export function safeFilePreview(source: string): string {
    const html = DOMPurify.sanitize(source.slice(0, 524288), {
        USE_PROFILES: { html: true },
        FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'form', 'base', 'meta', 'link'],
        FORBID_ATTR: ['action', 'formaction', 'srcdoc', 'ping'],
    });
    return `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; font-src data:; form-action 'none'; base-uri 'none'"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>${html}</body></html>`;
}
