type MermaidInstance = typeof import('mermaid').default;

let mermaidInstance: MermaidInstance | null = null;

export const getMermaid = async () => {
    if (!mermaidInstance) {
        const mod = await import('mermaid');
        mermaidInstance = mod.default;
    }
    return mermaidInstance;
};
