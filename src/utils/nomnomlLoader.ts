let nomnomlInstance = null;

export const getNomnoml = async () => {
    if (!nomnomlInstance) {
        const mod = await import('nomnoml');
        nomnomlInstance = mod.default || mod;
    }
    return nomnomlInstance;
};
