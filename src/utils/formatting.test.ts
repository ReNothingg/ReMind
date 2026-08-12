import { describe, expect, it } from 'vitest';

import { formatText, formatUserMessageText, highlightCode, refreshCodeLineNumbers, stripThinkingBlocks } from './formatting';

describe('stripThinkingBlocks', () => {
    it('removes completed thinking blocks from copied responses', () => {
        const response = '<think data-open="100" data-close="674">Internal reasoning</think>Final answer';

        expect(stripThinkingBlocks(response)).toBe('Final answer');
    });

    it('removes unfinished thinking blocks from copied responses', () => {
        expect(stripThinkingBlocks('Visible answer\n\n<think data-open="100">Internal reasoning')).toBe('Visible answer');
    });

    it('preserves responses without thinking blocks', () => {
        expect(stripThinkingBlocks('Final answer')).toBe('Final answer');
    });
});

describe('formatText', () => {
    it('renders assistant display math in a dedicated scrollable source wrapper', () => {
        const html = formatText('$$123456789 \\times 987654321 = 121932631112635269$$');
        const container = document.createElement('div');
        container.innerHTML = html;
        const formula = container.querySelector<HTMLElement>(
            '.markdown-latex-source[data-latex-display="true"]',
        );

        expect(formula?.querySelector('.katex-display')).not.toBeNull();
        expect(formula?.getAttribute('tabindex')).toBe('0');
        expect(container.textContent).not.toContain('$$');
    });

    it('renders fenced code blocks with language metadata', () => {
        const html = formatText('```python\nfrom pathlib import Path\n```');

        expect(html).toContain('class="code-block"');
        expect(html).toContain('Python');
        expect(html).toContain('language-python');
        expect(html).toContain('token keyword');
    });

    it('adds a safe run control and console shell only to Python code blocks', () => {
        const pythonContainer = document.createElement('div');
        pythonContainer.innerHTML = formatText('```python\nprint("ok")\n```');
        const textContainer = document.createElement('div');
        textContainer.innerHTML = formatText('```text\nplain text\n```');

        expect(pythonContainer.querySelector('.run-code-btn')?.textContent).toBe('Run');
        expect(pythonContainer.querySelector('.code-execution-console')?.hasAttribute('hidden')).toBe(true);
        expect(textContainer.querySelector('.run-code-btn')).toBeNull();
        expect(textContainer.querySelector('.code-execution-console')).toBeNull();
    });

    it('includes line numbers for an unfinished streamed code fence', () => {
        const html = formatText('```text\nfirst line\nsecond line');
        const container = document.createElement('div');
        container.innerHTML = html;

        expect(container.querySelectorAll('.line-numbers-rows > span')).toHaveLength(2);
    });

    it('only renders a collapse control when code exceeds the collapsed line limit', () => {
        const shortHtml = formatText('```python\nfirst\nsecond\n```');
        const longCode = Array.from({ length: 10 }, (_, index) => `line_${index + 1}`).join('\n');
        const longHtml = formatText(`\`\`\`python\n${longCode}\n\`\`\``);

        expect(shortHtml).not.toContain('toggle-code-btn');
        expect(longHtml).toContain('toggle-code-btn');
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

    it('sanitizes executable HTML and unsafe links in rendered documents', () => {
        const html = formatText([
            '# Safe document',
            '<script>window.compromised = true</script>',
            '<img src="x" onerror="window.compromised = true">',
            '[unsafe](javascript:alert(1))',
        ].join('\n'));
        const container = document.createElement('div');
        container.innerHTML = html;

        expect(container.querySelector('h1')?.textContent).toBe('Safe document');
        expect(container.querySelector('script')).toBeNull();
        expect(container.querySelector('[onerror]')).toBeNull();
        expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    });

    it('renders safe hex color tokens with an inline swatch outside code blocks', () => {
        const html = formatText([
            'Indigo is #4B0082, and a short color is #abc.',
            '',
            '```text',
            '#ff0000',
            '```',
        ].join('\n'));
        const container = document.createElement('div');
        container.innerHTML = html;

        const swatches = container.querySelectorAll('.chat-color-swatch');
        expect(swatches).toHaveLength(2);
        expect(swatches[0]?.getAttribute('aria-hidden')).toBe('true');
        expect((swatches[0] as HTMLElement).style.backgroundColor).toBe('rgb(75, 0, 130)');
        expect(container.querySelector('.chat-color-token')?.firstElementChild?.className)
            .toBe('chat-color-value');
        expect(container.querySelector('.chat-color-token')?.lastElementChild?.className)
            .toBe('chat-color-swatch');
        expect(container.querySelector('pre .chat-color-swatch')).toBeNull();
        expect(container.querySelector('.chat-color-value')?.textContent).toBe('#4B0082');
    });

    it('encodes interactive visualization fragments instead of executing them in the message DOM', () => {
        const source = '<button id="run">Run</button><script>window.ran = true</script>';
        const html = formatText(`\`\`\`visualize:Counter lab\n${source}\n\`\`\``);
        const container = document.createElement('div');
        container.innerHTML = html;
        const host = container.querySelector('.visualize-instance-host');
        const encoded = host?.getAttribute('data-visualize-source-b64') || '';
        const decoded = new TextDecoder().decode(
            Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0))
        );

        expect(host?.getAttribute('data-visualize-title')).toBe('Counter lab');
        expect(host?.getAttribute('data-visualize-mode')).toBe('normal');
        expect(decoded).toContain(source);
        expect(container.querySelector('script')).toBeNull();
    });

    it('supports wide interactive visualization blocks', () => {
        const html = formatText('```visualize-wide:Comparison\n<section>Compare</section>\n```');
        const container = document.createElement('div');
        container.innerHTML = html;

        expect(container.querySelector('.visualize-instance-host')?.getAttribute('data-visualize-mode')).toBe('wide');
    });

    it('recognizes detached and whitespace-separated visualize fence markers', () => {
        const variants = [
            '```\nvisualize:Detached title\n<section>Detached</section>\n```',
            '` ` ` visualize:Spaced title\n<section>Spaced</section>\n` ` `',
            '\\`\\`\\`visualize:Escaped title\n<section>Escaped</section>\n\\`\\`\\`',
        ];

        variants.forEach((source) => {
            const container = document.createElement('div');
            container.innerHTML = formatText(source);

            expect(container.querySelector('.visualize-instance-host')).not.toBeNull();
            expect(container.querySelector('.code-block')).toBeNull();
            expect(container.textContent).not.toContain('visualize:');
        });
    });

    it('keeps an unfinished visualize stream out of the main message DOM', () => {
        const html = formatText([
            '```visualize:Loading lab',
            '<button>Unsafe partial markup</button>',
            '<script>window.partialRan = true</script>',
        ].join('\n'));
        const container = document.createElement('div');
        container.innerHTML = html;

        expect(container.querySelector('.interactive-placeholder[data-tool="visualize"]')).not.toBeNull();
        expect(container.querySelector('button')).toBeNull();
        expect(container.querySelector('script')).toBeNull();
        expect(container.textContent).not.toContain('Unsafe partial markup');
    });

    it('extracts the reported beatbox visualization without swallowing its trailing prose', () => {
        const source = [
            '```visualize:Битбокс-секвенсор',
            '<div class="card p-3">',
            '  <div class="d-flex justify-content-between align-items-center mb-3">',
            '    <h3 class="h5 m-0">Ритм-станция</h3>',
            '    <button id="playBtn" class="btn btn-primary">Play</button>',
            '  </div>',
            '</div>',
            '<script>document.getElementById("playBtn").onclick = () => {};</script>',
            '```',
            '',
            'Сделал для тебя простой интерфейс в виде секвенсора.',
        ].join('\n');
        const container = document.createElement('div');
        container.innerHTML = formatText(source);

        const host = container.querySelector('.visualize-instance-host');
        expect(host?.getAttribute('data-visualize-title')).toBe('Битбокс-секвенсор');
        expect(container.querySelector('.code-block')).toBeNull();
        expect(container.textContent).toContain('Сделал для тебя простой интерфейс');
        expect(container.textContent).not.toContain('visualize:Битбокс');
    });
});

describe('formatUserMessageText', () => {
    it('renders user inline and display LaTeX while preserving its source metadata', () => {
        const html = formatUserMessageText(
            'Реши $x^2 + 1$\n\n$$\\frac{8,888,888}{2,222,222} = 4$$',
            { renderMarkdown: true },
        );
        const container = document.createElement('div');
        container.innerHTML = html;
        const inlineFormula = container.querySelector(
            '.markdown-latex-source[data-latex-display="false"] .katex',
        );
        const displayFormula = container.querySelector<HTMLElement>(
            '.markdown-latex-source[data-latex-display="true"]',
        );

        expect(inlineFormula).not.toBeNull();
        expect(displayFormula?.querySelector('.katex-display')).not.toBeNull();
        expect(displayFormula?.getAttribute('data-latex-source'))
            .toBe('\\frac{8,888,888}{2,222,222} = 4');
        expect(container.textContent).not.toContain('$$');
    });

    it('does not interpret dollar-delimited text inside user code blocks as LaTeX', () => {
        const html = formatUserMessageText('```text\n$total + $tax\n```', {
            renderMarkdown: true,
        });
        const container = document.createElement('div');
        container.innerHTML = html;

        expect(container.querySelector('.markdown-latex-source')).toBeNull();
        expect(container.querySelector('code')?.textContent).toContain('$total + $tax');
    });

    it('renders LaTeX in an enabled user quote without enabling trusted KaTeX links', () => {
        const html = formatUserMessageText(
            '> Формула: $x^2$ и $\\href{javascript:alert(1)}{unsafe}$\n\nПроверь',
            { renderMarkdown: true },
        );
        const container = document.createElement('div');
        container.innerHTML = html;

        expect(container.querySelector('.user-message-quote-display .katex')).not.toBeNull();
        expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
        expect(container.querySelector('script')).toBeNull();
    });

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
            <pre class="code-line-numbered language-python">
                <code class="language-python" data-highlighted="yes">from pathlib import Path</code>
                <span class="line-numbers-rows"><span></span></span>
            </pre>
        `;

        highlightCode(container);

        const code = container.querySelector('code');
        expect(code?.querySelector('.token.keyword')?.textContent).toBe('from');
        expect(container.querySelectorAll('.line-numbers-rows')).toHaveLength(1);
    });

    it('restores fallback rows after a highlighter rebuild removes them', () => {
        const container = document.createElement('div');
        container.innerHTML = `
            <pre class="code-line-numbered language-python"><code class="language-python">print('one')\nprint('two')</code></pre>
        `;

        highlightCode(container);

        expect(container.querySelectorAll('.line-numbers-rows > span')).toHaveLength(2);
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
