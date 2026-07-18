const BLOCK_ELEMENTS = new Set([
    'ADDRESS', 'ARTICLE', 'ASIDE', 'BLOCKQUOTE', 'DIV', 'DL', 'FIELDSET',
    'FIGCAPTION', 'FIGURE', 'FOOTER', 'FORM', 'H1', 'H2', 'H3', 'H4',
    'H5', 'H6', 'HEADER', 'HR', 'MAIN', 'NAV', 'OL', 'P', 'PRE',
    'SECTION', 'TABLE', 'UL',
]);

const escapeMarkdownText = (value: string) => value
    .replace(/\u200b/g, '')
    .replace(/\\/g, '\\\\')
    .replace(/(\[|\]|[`*_<>])/g, '\\$1');

const getLatexSource = (element: Element) => (
    element.querySelector('annotation[encoding="application/x-tex"]')?.textContent?.trim() || ''
);

const serializeChildren = (node: ParentNode): string => (
    Array.from(node.childNodes).map((child) => serializeNode(child)).join('')
);

const serializeInlineCode = (value: string) => {
    const delimiter = value.includes('`') ? '``' : '`';
    const padding = value.startsWith(' ') || value.endsWith(' ') ? ' ' : '';
    return `${delimiter}${padding}${value}${padding}${delimiter}`;
};

const serializeCodeBlock = (element: HTMLElement) => {
    const code = element.querySelector('.code-block-content code')?.textContent || '';
    const language = element.dataset.language || '';
    const filename = element.dataset.sourceFilename || '';
    const info = `${language}${filename ? `:${filename}` : ''}`.trim();
    const fence = code.includes('```') ? '````' : '```';
    return `${fence}${info}\n${code.replace(/\n$/, '')}\n${fence}\n\n`;
};

const escapeTableCell = (value: string) => value
    .replace(/\s*\n\s*/g, '<br>')
    .replace(/\|/g, '\\|')
    .trim();

const serializeTable = (table: HTMLTableElement) => {
    const rows = Array.from(table.rows).map((row) => (
        Array.from(row.cells).map((cell) => escapeTableCell(serializeChildren(cell)))
    ));
    if (rows.length === 0) return '';

    const columnCount = Math.max(...rows.map((row) => row.length), 1);
    const normalizedRows = rows.map((row) => (
        Array.from({ length: columnCount }, (_, index) => row[index] || '')
    ));
    const header = normalizedRows[0];
    const separator = Array.from({ length: columnCount }, () => '---');
    const body = normalizedRows.slice(1);
    return [header, separator, ...body]
        .map((row) => `| ${row.join(' | ')} |`)
        .join('\n') + '\n\n';
};

const directListContent = (item: HTMLLIElement) => (
    Array.from(item.childNodes)
        .filter((node) => !(
            node instanceof HTMLElement
            && (node.tagName === 'UL' || node.tagName === 'OL')
        ))
        .map((node) => serializeNode(node))
        .join('')
        .replace(/^\s+|\s+$/g, '')
);

const serializeList = (list: HTMLOListElement | HTMLUListElement, depth = 0): string => {
    const ordered = list.tagName === 'OL';
    const start = ordered ? Number.parseInt(list.getAttribute('start') || '1', 10) : 1;
    const indent = '  '.repeat(depth);
    const lines: string[] = [];

    Array.from(list.children).forEach((child, index) => {
        if (!(child instanceof HTMLLIElement)) return;
        const checkbox = Array.from(child.children).find((element) => (
            element instanceof HTMLInputElement && element.type === 'checkbox'
        ));
        const taskPrefix = checkbox instanceof HTMLInputElement
            ? `[${checkbox.checked ? 'x' : ' '}] `
            : '';
        const marker = ordered ? `${start + index}. ` : '- ';
        lines.push(`${indent}${marker}${taskPrefix}${directListContent(child)}`.trimEnd());

        Array.from(child.children).forEach((nested) => {
            if (nested instanceof HTMLUListElement || nested instanceof HTMLOListElement) {
                lines.push(serializeList(nested, depth + 1).trimEnd());
            }
        });
    });

    return `${lines.join('\n')}\n\n`;
};

const serializeNode = (node: Node): string => {
    if (node.nodeType === Node.TEXT_NODE) {
        const value = node.textContent || '';
        if (/^\s+$/.test(value) && value.includes('\n')) return '';
        return escapeMarkdownText(value);
    }
    if (!(node instanceof HTMLElement)) return '';

    if (node.classList.contains('code-block')) {
        return serializeCodeBlock(node);
    }
    if (node.dataset.latexSource !== undefined) {
        const latex = node.dataset.latexSource || '';
        return node.dataset.latexDisplay === 'true'
            ? `\n$$\n${latex}\n$$\n`
            : `$${latex}$`;
    }
    if (node.classList.contains('table-wrapper')) {
        const table = node.querySelector('table');
        return table instanceof HTMLTableElement ? serializeTable(table) : '';
    }
    if (node.classList.contains('katex-display')) {
        const latex = getLatexSource(node);
        return latex ? `\n$$\n${latex}\n$$\n` : '';
    }
    if (node.classList.contains('katex')) {
        const latex = getLatexSource(node);
        return latex ? `$${latex}$` : '';
    }

    const children = () => serializeChildren(node);
    switch (node.tagName) {
        case 'H1':
        case 'H2':
        case 'H3':
        case 'H4':
        case 'H5':
        case 'H6': {
            const level = Number.parseInt(node.tagName.slice(1), 10);
            return `${'#'.repeat(level)} ${children().trim()}\n\n`;
        }
        case 'P':
            return `${children().trim()}\n\n`;
        case 'STRONG':
        case 'B':
            return `**${children()}**`;
        case 'EM':
        case 'I':
            return `*${children()}*`;
        case 'DEL':
        case 'S':
            return `~~${children()}~~`;
        case 'CODE':
            return serializeInlineCode(node.textContent || '');
        case 'PRE': {
            const code = node.textContent || '';
            const fence = code.includes('```') ? '````' : '```';
            return `${fence}\n${code.replace(/\n$/, '')}\n${fence}\n\n`;
        }
        case 'A': {
            const href = node.getAttribute('href') || '';
            const title = node.getAttribute('title');
            return href
                ? `[${children()}](${href}${title ? ` "${title.replace(/"/g, '\\"')}"` : ''})`
                : children();
        }
        case 'IMG': {
            const source = node.getAttribute('src') || '';
            const alt = node.getAttribute('alt') || '';
            const title = node.getAttribute('title');
            return source
                ? `![${alt}](${source}${title ? ` "${title.replace(/"/g, '\\"')}"` : ''})`
                : '';
        }
        case 'BR':
            return '\n';
        case 'HR':
            return '\n---\n\n';
        case 'BLOCKQUOTE':
            return `${children().trim().split('\n').map((line) => `> ${line}`).join('\n')}\n\n`;
        case 'UL':
        case 'OL':
            return serializeList(node as HTMLUListElement | HTMLOListElement);
        case 'TABLE':
            return serializeTable(node as HTMLTableElement);
        case 'BUTTON':
        case 'INPUT':
        case 'CANVAS':
        case 'SVG':
            return '';
        default: {
            const content = children();
            return BLOCK_ELEMENTS.has(node.tagName) ? `${content}\n` : content;
        }
    }
};

export const renderedMarkdownToSource = (root: HTMLElement): string => (
    serializeChildren(root)
        .replace(/[ \t]+\n/g, '\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim()
);
