type NomnomlModule = typeof import('nomnoml');

let nomnomlInstance: NomnomlModule | null = null;

export const getNomnoml = async () => {
    if (!nomnomlInstance) {
        nomnomlInstance = await import('nomnoml');
    }
    return nomnomlInstance;
};
