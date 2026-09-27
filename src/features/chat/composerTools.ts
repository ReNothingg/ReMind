export interface ComposerTool {
    id: string;
    label: string;
    removeLabel: string;
}

export function toolMarker(id: string): string {
    return `@{${id}}`;
}

export function readComposerTools(value: string, tools: readonly ComposerTool[]) {
    const selected: ComposerTool[] = [];
    const text = value.replace(/@\{([a-z_]+)\}/g, (marker: string, id: string) => {
        const tool = tools.find((candidate) => candidate.id === id);
        if (!tool) return marker;
        selected.push(tool);
        return '';
    });
    return { text, selected };
}


const TOOL_ICONS: Record<string, string> = {
    files: 'M14 2H5v20h14V7ZM14 2v5h5M8 12h8M8 16h6',
    data: 'M4 4h16v16H4ZM4 9h16M9 4v16M4 14h16',
    workflow: 'M8 5h12M8 12h12M8 19h12M3 5h1M3 12h1M3 19h1',
    web: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM3 12h18M12 3c4 5 4 13 0 18-4-5-4-13 0-18Z',
    visualize: 'M3 3h18v14H3ZM8 21l4-4 4 4M7 12l3-4 4 5 3-6',
    github: 'M9 19c-5 1-5-3-7-3M15 22v-4a4 4 0 0 0-1-3c4 0 6-2 6-5a4 4 0 0 0-1-3 4 4 0 0 0 0-4s-2 0-4 2a13 13 0 0 0-6 0C7 3 5 3 5 3a4 4 0 0 0 0 4 4 4 0 0 0-1 3c0 3 2 5 6 5a4 4 0 0 0-1 3v4',
    python: 'm8 7-5 5 5 5m8-10 5 5-5 5M14 4l-4 16',
    image_analysis: 'M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M5 12s3-4 7-4 7 4 7 4-3 4-7 4-7-4-7-4Zm7-1v2',
    canvas: 'M14 2H5v20h14V7ZM14 2v5h5M8 12h8M8 16h6',
    charts: 'M4 3v18h17M8 16v-4m5 4V7m5 9V4',
    diagrams: 'M8 2h8v6H8ZM2 16h8v6H2Zm12 0h8v6h-8ZM12 8v4M6 16v-4h12v4',
    beatbox: 'M4 9v6m4-10v14m4-17v20m4-17v14m4-10v6',
    quiz: 'M4 3h16v18H4ZM9 8a3 3 0 1 1 5 2c-2 1-2 2-2 3m0 3v1',
};

export function toolIconPath(id: string): string {
    return TOOL_ICONS[id] || 'M14 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-9M16 5h6M19 2v6M3 16l5-5 4 4 3-3 6 6';
}

export function isKnownComposerTool(id: string): boolean {
    return Object.hasOwn(TOOL_ICONS, id) || id === 'demo_image' || id === 'mindart';
}
