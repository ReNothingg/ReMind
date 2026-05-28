import { describe, expect, it } from 'vitest';

import { formatText, highlightCode } from './formatting';

describe('formatText', () => {
    it('renders fenced code blocks with language metadata', () => {
        const html = formatText('```python\nfrom aiogram.types import InlineKeyboardButton\n```');

        expect(html).toContain('class="code-block"');
        expect(html).toContain('Python');
        expect(html).toContain('language-python');
    });
});

describe('highlightCode', () => {
    it('re-highlights code blocks after Prism marked them as already highlighted', () => {
        const container = document.createElement('div');
        container.innerHTML = `
            <pre class="line-numbers language-python">
                <code class="language-python" data-highlighted="yes">from aiogram.types import InlineKeyboardButton</code>
                <span class="line-numbers-rows"><span></span></span>
            </pre>
        `;

        highlightCode(container);

        const code = container.querySelector('code');
        expect(code?.querySelector('.token.keyword')?.textContent).toBe('from');
        expect(container.querySelectorAll('.line-numbers-rows')).toHaveLength(1);
    });
});
