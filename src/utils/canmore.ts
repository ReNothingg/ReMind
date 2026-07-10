export function stripCanmoreToolMarkup(text: unknown): string {
    const cleaned = String(text || '')
        .replace(/```canmore\s*[\s\S]*?```/gi, '')
        .replace(/```[^\n`]*\n?[\s\S]*?canmore\.(?:create_textdoc|update_textdoc|comment_textdoc)[\s\S]*?```/gi, '')
        .replace(/<canmore(?:\s[^>]*)?>[\s\S]*?<\/canmore>/gi, '')
        .trim();
    return cleaned
        .split(/\n{2,}/)
        .filter((paragraph) => !paragraph.toLowerCase().includes('canmore.'))
        .join('\n\n')
        .trim();
}
