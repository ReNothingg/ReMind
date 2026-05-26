import { describe, expect, it } from 'vitest';

import { buildSvgPreviewDocument, sanitizeSvgMarkup } from './svgPreview';

describe('sanitizeSvgMarkup', () => {
    it('preserves safe SVG structure needed for previewing', () => {
        const input = `
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
                <defs>
                    <linearGradient id="grad">
                        <stop offset="0%" stop-color="#0ea5e9" />
                        <stop offset="100%" stop-color="#2563eb" />
                    </linearGradient>
                </defs>
                <rect width="120" height="120" rx="24" fill="url(#grad)" />
                <text x="60" y="68" text-anchor="middle" font-size="24" fill="#fff">SVG</text>
            </svg>
        `;

        const result = sanitizeSvgMarkup(input);

        expect(result.error).toBeUndefined();
        expect(result.sanitizedMarkup).toContain('<linearGradient');
        expect(result.sanitizedMarkup).toContain('fill="url(#grad)"');
        expect(result.sanitizedMarkup).toContain('<text');
    });

    it('drops executable and external SVG content', () => {
        const input = `
            <svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" onload="alert(1)">
                <script>alert(1)</script>
                <foreignObject><div>bad</div></foreignObject>
                <image href="https://evil.example/x.png" width="10" height="10" />
                <rect width="10" height="10" fill="red" onclick="stealCookies()" />
                <linearGradient id="grad" xlink:href="https://evil.example/g.svg"></linearGradient>
            </svg>
        `;

        const result = sanitizeSvgMarkup(input);

        expect(result.error).toBeUndefined();
        expect(result.sanitizedMarkup).toContain('<rect');
        expect(result.sanitizedMarkup).not.toContain('onload');
        expect(result.sanitizedMarkup).not.toContain('onclick');
        expect(result.sanitizedMarkup).not.toContain('<script');
        expect(result.sanitizedMarkup).not.toContain('foreignObject');
        expect(result.sanitizedMarkup).not.toContain('<image');
        expect(result.sanitizedMarkup).not.toContain('https://evil.example');
    });

    it('rejects invalid non-svg markup', () => {
        const result = sanitizeSvgMarkup('<div>nope</div>');

        expect(result.sanitizedMarkup).toBeNull();
        expect(result.error).toContain('SVG');
    });
});

describe('buildSvgPreviewDocument', () => {
    it('embeds the sanitized SVG inside a locked-down srcdoc shell', () => {
        const documentMarkup = buildSvgPreviewDocument(
            '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
            'SVG preview',
            'rgb(20, 24, 30)'
        );

        expect(documentMarkup).toContain("Content-Security-Policy");
        expect(documentMarkup).toContain("default-src 'none'");
        expect(documentMarkup).toContain('background: rgb(20, 24, 30);');
        expect(documentMarkup).toContain('<svg xmlns="http://www.w3.org/2000/svg"></svg>');
    });
});
