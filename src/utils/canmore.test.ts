import { describe, expect, it } from 'vitest';

import { stripCanmoreToolMarkup } from './canmore';

describe('stripCanmoreToolMarkup', () => {
    it('removes a bare arguments object emitted in a Canmore fence', () => {
        const message = `До вызова.

\`\`\`Canmore
{"name":"maze-generator","type":"code/javascript","content":"import React from 'react'"}
\`\`\`

После вызова.`;

        expect(stripCanmoreToolMarkup(message)).toBe('До вызова.\n\nПосле вызова.');
    });
});
