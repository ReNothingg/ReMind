const SAFE_CLIPBOARD_IMAGE_EXTENSIONS: Record<string, string> = {
    'image/gif': 'gif',
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/webp': 'webp',
};

export function imageFilesFromClipboard(
    items: ArrayLike<DataTransferItem> | null | undefined,
    timestamp = Date.now(),
    baseName = 'image',
): File[] {
    const safeBaseName = baseName
        .normalize('NFKC')
        .replace(/[^\p{L}\p{N}_-]+/gu, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 48) || 'image';
    return Array.from(items || []).flatMap((item, index) => {
        if (item.kind !== 'file') {
            return [];
        }

        const file = item.getAsFile();
        const mimeType = String(item.type || file?.type || '').toLowerCase();
        const extension = SAFE_CLIPBOARD_IMAGE_EXTENSIONS[mimeType];
        if (!file || !extension) {
            return [];
        }

        const hasUsefulName = Boolean(file.name && /\.[a-z0-9]{2,5}$/i.test(file.name));
        if (hasUsefulName) {
            return [file];
        }

        return [new File(
            [file],
            `${safeBaseName}-${timestamp}-${index + 1}.${extension}`,
            { type: mimeType, lastModified: timestamp },
        )];
    });
}
