import { describe, expect, it } from 'vitest';

import { fileService } from './fileService';

describe('fileService', () => {
    it('validates individual files', () => {
        expect(fileService.validateFile(null)).toMatchObject({
            valid: false,
            error: expect.stringContaining('Файл'),
        });

        expect(fileService.validateFile({ size: 101 * 1024 * 1024 })).toMatchObject({
            valid: false,
            error: expect.stringContaining('100MB'),
        });

        expect(fileService.validateFile({ size: 1 })).toEqual({ valid: true });
    });

    it('validates file collections and enforces max count', () => {
        expect(fileService.validateFiles([])).toMatchObject({
            valid: false,
            error: expect.stringContaining('Файлы'),
        });

        const tooMany = Array.from({ length: fileService.MAX_FILES + 1 }, () => ({ size: 1 }));
        expect(fileService.validateFiles(tooMany)).toMatchObject({
            valid: false,
            error: expect.stringContaining(String(fileService.MAX_FILES)),
        });

        const files = [{ size: 1 }, { size: 10 }];
        expect(fileService.validateFiles(files)).toEqual({ valid: true });
    });

    it('detects text, image, and 3d model files', () => {
        expect(fileService.isTextFile({ name: 'notes.md', type: 'application/octet-stream' })).toBe(true);
        expect(fileService.isTextFile({ name: 'plain.bin', type: 'text/plain' })).toBe(true);
        expect(fileService.isTextFile({ name: '', type: 'application/octet-stream' })).toBe(false);

        expect(fileService.isImageFile({ type: 'image/png' })).toBe(true);
        expect(fileService.isImageFile({ type: 'application/pdf' })).toBe(false);

        expect(fileService.is3DModelFile({ name: 'scene.glb', type: 'application/octet-stream' })).toBe(true);
        expect(fileService.is3DModelFile({ name: 'mesh.bin', type: 'model/gltf+json' })).toBe(true);
        expect(fileService.is3DModelFile({ name: 'mesh.txt', type: 'text/plain' })).toBe(false);
    });

    it('formats file sizes with clamped decimals', () => {
        expect(fileService.formatFileSize(0)).toBe('0 Bytes');
        expect(fileService.formatFileSize(1536)).toBe('1.5 KB');
        expect(fileService.formatFileSize(1024, -1)).toBe('1 KB');
    });

    it('maps icon paths and escapes html', () => {
        expect(fileService.getFileIconPath('pdf')).toContain('/pdf.svg');
        expect(fileService.getFileIconPath('unknown')).toContain('/file.svg');
        expect(fileService.escapeHtml(`5 < 7 & "quote"`)).toBe('5 &lt; 7 &amp; &quot;quote&quot;');
    });
});
