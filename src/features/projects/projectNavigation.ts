const PROJECT_PATH = /^\/projects\/([a-f0-9]{32})\/?$/;

export function projectIdForPath(path: string): string | null {
  return PROJECT_PATH.exec(path)?.[1] ?? null;
}

export function projectPath(id: string): string {
  return `/projects/${encodeURIComponent(id)}`;
}
