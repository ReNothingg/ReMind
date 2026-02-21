let mermaidInstance = null;

export const getMermaid = async () => {
    if (!mermaidInstance) {
        const mod = await import('mermaid');
        mermaidInstance = mod.default || mod;
    }
    return mermaidInstance;
};
