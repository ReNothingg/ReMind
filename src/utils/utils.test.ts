import { describe, expect, it } from 'vitest';

import { sanitizeGeneratedDiagramSvg } from './utils';

describe('sanitizeGeneratedDiagramSvg', () => {
    it('removes executable and externally loaded content from generated diagrams', () => {
        const sanitized = sanitizeGeneratedDiagramSvg(`
            <svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">
                <script>alert(1)</script>
                <foreignObject><div>unsafe</div></foreignObject>
                <image href="https://example.test/tracker.png" />
                <a href="javascript:alert(1)"><text>unsafe link</text></a>
                <rect width="10" height="10" fill="red" />
            </svg>
        `);
        const container = document.createElement('div');
        container.innerHTML = sanitized;

        expect(container.querySelector('svg')).not.toBeNull();
        expect(container.querySelector('rect')).not.toBeNull();
        expect(container.querySelector('script, foreignObject, image')).toBeNull();
        expect(container.querySelector('[onload], [href], [xlink\\:href]')).toBeNull();
    });
});
