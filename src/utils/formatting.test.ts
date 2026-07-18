import { describe, expect, it } from 'vitest';

import { formatText, formatUserMessageText, highlightCode, refreshCodeLineNumbers } from './formatting';

describe('formatText', () => {
    it('renders fenced code blocks with language metadata', () => {
        const html = formatText('```python\nfrom pathlib import Path\n```');

        expect(html).toContain('class="code-block"');
        expect(html).toContain('Python');
        expect(html).toContain('language-python');
        expect(html).toContain('token keyword');
    });

    it('normalizes common language aliases before highlighting', () => {
        const html = formatText('```ts\nconst enabled: boolean = true;\n```');

        expect(html).toContain('language-typescript');
        expect(html).toContain('token keyword');
        expect(html).toContain('token boolean');
    });

    it('keeps unsupported languages readable without fake highlighting', () => {
        const html = formatText('```madeup\n<unsafe>& value\n```');

        expect(html).toContain('language-madeup');
        expect(html).toContain('&lt;unsafe&gt;&amp; value');
        expect(html).not.toContain('token keyword');
    });

    it('keeps multiline thoughts inside an encoded host instead of leaking them into the answer', () => {
        const thought = "**Considering Maze Aesthetics**\nI've started checking options.\n\n**Rendering Visually**\nThe `render` function is ready.";
        const html = formatText(`<think data-open="100" data-close="674">${thought}</think>Final answer`);
        const container = document.createElement('div');
        container.innerHTML = html;
        const host = container.querySelector('.think-instance-host');
        const encoded = host?.getAttribute('data-think-content-b64') || '';

        expect(decodeURIComponent(escape(atob(encoded)))).toBe(thought);
        expect(container.textContent).toBe('Final answer');
        expect(html).not.toContain('Rendering Visually');
    });
});

describe('formatUserMessageText', () => {
    it('renders a leading quoted block separately from the user message body', () => {
        const html = formatUserMessageText('> Привет! Готов помочь\n\nА что это?');

        expect(html).toContain('class="user-message-quote-display"');
        expect(html).toContain('<blockquote>Привет! Готов помочь</blockquote>');
        expect(html).toContain('А что это?');
    });

    it('keeps regular user messages unchanged when there is no leading quote', () => {
        const html = formatUserMessageText('А что это?');

        expect(html).not.toContain('user-message-quote-display');
        expect(html).toBe('А что это?');
    });

    it('renders enabled user Markdown without allowing executable markup', () => {
        const html = formatUserMessageText(
            '**Важно**\n\n[опасная ссылка](javascript:alert(1))\n\n<img src=x onerror=alert(1)>',
            { renderMarkdown: true }
        );
        const container = document.createElement('div');
        container.innerHTML = html;

        expect(html).toContain('<strong>Важно</strong>');
        expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
        expect(container.querySelector('[onerror]')).toBeNull();
        expect(container.querySelector('img')).toBeNull();
    });
});

describe('highlightCode', () => {
    it('re-highlights code blocks after Prism marked them as already highlighted', () => {
        const container = document.createElement('div');
        container.innerHTML = `
            <pre class="line-numbers language-python">
                <code class="language-python" data-highlighted="yes">from pathlib import Path</code>
                <span class="line-numbers-rows"><span></span></span>
            </pre>
        `;

        highlightCode(container);

        const code = container.querySelector('code');
        expect(code?.querySelector('.token.keyword')?.textContent).toBe('from');
        expect(container.querySelectorAll('.line-numbers-rows')).toHaveLength(1);
    });
});

describe('refreshCodeLineNumbers', () => {
    it('restores missing line number rows without changing the code text', () => {
        const container = document.createElement('div');
        container.innerHTML = formatText('```python\nfrom pathlib import Path\nprint(Path.cwd())\n```');

        highlightCode(container);
        container.querySelector('.line-numbers-rows')?.remove();

        refreshCodeLineNumbers(container);

        const code = container.querySelector('code');
        expect(code?.textContent).toBe('from pathlib import Path\nprint(Path.cwd())\n');
        expect(container.querySelectorAll('.line-numbers-rows')).toHaveLength(1);
        expect(container.querySelectorAll('.line-numbers-rows > span')).toHaveLength(2);
    });
});
