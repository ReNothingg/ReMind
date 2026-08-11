import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
    buildVisualizationDocument,
    readVisualizationContext,
    renderMathInVisualizationFragment,
} from './visualizationRuntime';

describe('visualization runtime', () => {
    beforeEach(() => {
        document.documentElement.dataset.theme = 'dark';
        document.documentElement.dataset.accentColor = 'purple';
        document.documentElement.style.setProperty('--color-bg-main', '#212121');
        document.documentElement.style.setProperty('--color-text-primary', '#f4f4f5');
        document.documentElement.style.setProperty('--color-accent', '#8b5cf6');
        Object.defineProperty(window, 'matchMedia', {
            configurable: true,
            value: vi.fn(() => ({ matches: true })),
        });
    });

    it('maps ReMind appearance fields and tokens into the widget context', () => {
        const context = readVisualizationContext({
            interface_language: 'ar',
            accentColor: 'purple',
            compactMode: true,
            highContrast: true,
        });

        expect(context.appearance).toMatchObject({
            theme: 'dark',
            locale: 'ar',
            direction: 'rtl',
            accentColor: 'purple',
            compactMode: true,
            highContrast: true,
            reducedMotion: true,
        });
        expect(context.tokens['--background']).toBe('#212121');
        expect(context.tokens['--foreground']).toBe('#f4f4f5');
        expect(context.tokens['--primary']).toBe('#8b5cf6');
    });

    it('builds a script sandbox document with a deny-by-default CSP', () => {
        const context = readVisualizationContext({ interface_language: 'en' });
        const documentSource = buildVisualizationDocument({
            fragment: '<button class="btn">Count</button><script>let count = 0</script>',
            context,
            channelId: 'channel-safe',
        });

        expect(documentSource).toContain("default-src 'none'");
        expect(documentSource).toContain("connect-src 'none'");
        expect(documentSource).toContain("frame-src 'none'");
        expect(documentSource).toContain('sendFollowUpMessage');
        expect(documentSource).toContain('renderMathElement');
        expect(documentSource).toContain('font-src data: https://fonts.gstatic.com https://fonts.bunny.net https://cdn.jsdelivr.net');
        expect(documentSource).toContain('channel-safe');
        expect(documentSource).toContain('<button class="btn">Count</button>');
        expect(documentSource).toContain('.d-flex { display: flex; }');
        expect(documentSource).toContain('.justify-content-between { justify-content: space-between; }');
        expect(documentSource).not.toContain('allow-same-origin');
    });

    it('renders static LaTeX while leaving code and script content untouched', () => {
        const fragment = renderMathInVisualizationFragment([
            '<label>Жесткость пружины ($k$)</label>',
            '<p>$$F = -kx$$</p>',
            '<code>$code$</code>',
            '<script>const template = "$script$";</script>',
        ].join(''));

        expect(fragment).toContain('class="katex"');
        expect(fragment).not.toContain('($k$)');
        expect(fragment).not.toContain('$$F = -kx$$');
        expect(fragment).toContain('<code>$code$</code>');
        expect(fragment).toContain('const template = "$script$";');
    });
});
