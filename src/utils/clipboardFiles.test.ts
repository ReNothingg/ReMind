import { describe, expect, it } from 'vitest';

import { imageFilesFromClipboard } from './clipboardFiles';

const clipboardItem = (file: File, type = file.type): DataTransferItem => ({
    kind: 'file',
    type,
    getAsFile: () => file,
} as DataTransferItem);

describe('imageFilesFromClipboard', () => {
    it('accepts safe raster images and supplies a stable filename', () => {
        const source = new File(['png'], '', { type: 'image/png' });

        const result = imageFilesFromClipboard([clipboardItem(source)], 1234, 'pasted-image');

        expect(result).toHaveLength(1);
        expect(result[0].name).toBe('pasted-image-1234-1.png');
        expect(result[0].type).toBe('image/png');
    });

    it('rejects text and active SVG clipboard payloads', () => {
        const text = new File(['hello'], 'note.txt', { type: 'text/plain' });
        const svg = new File(['<svg/>'], 'image.svg', { type: 'image/svg+xml' });

        expect(imageFilesFromClipboard([
            clipboardItem(text),
            clipboardItem(svg),
        ])).toEqual([]);
    });
});
