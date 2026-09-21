export function artifactDownloadUrl(path: string): string {
    const url = new URL(path, window.location.origin);
    if (url.origin !== window.location.origin || url.username || url.password || !/^\/uploads\/[a-f0-9]{32}\.[a-z0-9]{1,12}$/.test(url.pathname) || url.search || url.hash) {
        throw new Error('invalid_artifact_url');
    }
    return url.toString();
}

export async function checkArtifactDownload(path: string): Promise<void> {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15_000);
    try {
        const response = await fetch(artifactDownloadUrl(path), { method: 'HEAD', credentials: 'include', redirect: 'error', signal: controller.signal });
        if (!response.ok) throw new Error(response.status === 404 ? 'artifact_unavailable' : 'artifact_download_failed');
        if (!response.headers.get('content-disposition')?.toLowerCase().startsWith('attachment')) throw new Error('artifact_download_failed');
    } finally {
        window.clearTimeout(timeout);
    }
}
