import { describe, expect, it } from 'vitest';

import { formatText } from './formatting';
import { renderedMarkdownToSource } from './markdownDom';

describe('renderedMarkdownToSource', () => {
    it('preserves rich Markdown structure edited in the rendered document', () => {
        const root = document.createElement('div');
        root.innerHTML = formatText([
            '# Original heading',
            '',
            'A **bold** paragraph with $E = mc^2$.',
            '',
            '- [x] Complete item',
            '- Pending item',
            '',
            '| Name | Value |',
            '| --- | --- |',
            '| Alpha | 1 |',
            '',
            '```mermaid:flow.mmd',
            'graph TD; A-->B',
            '```',
        ].join('\n'));
        const heading = root.querySelector('h1');
        if (heading) heading.textContent = 'Edited heading';

        const source = renderedMarkdownToSource(root);

        expect(source).toContain('# Edited heading');
        expect(source).toContain('**bold**');
        expect(source).toContain('$E = mc^2$');
        expect(source).toContain('- [x] Complete item');
        expect(source).toContain('| Name | Value |');
        expect(source).toContain('```mermaid:flow.mmd');
        expect(source).toContain('graph TD; A-->B');
    });

    it('serializes inserted rich HTML as Markdown text without executable attributes', () => {
        const root = document.createElement('div');
        root.innerHTML = '<p>Hello <strong>world</strong><img src="x" onerror="alert(1)"></p>';

        const source = renderedMarkdownToSource(root);

        expect(source).toBe('Hello **world**![](x)');
        expect(source).not.toContain('onerror');
    });
});
