export function safeGitHubUrl(value: unknown): string | null {
    if (typeof value !== 'string' || !value.trim()) {
        return null;
    }

    try {
        const url = new URL(value);
        if (
            url.protocol !== 'https:'
            || url.hostname.toLowerCase() !== 'github.com'
            || url.port
            || url.username
            || url.password
        ) {
            return null;
        }
        return url.toString();
    } catch {
        return null;
    }
}
