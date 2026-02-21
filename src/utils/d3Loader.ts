let d3Instance = null;

export const getD3 = async () => {
    if (!d3Instance) {
        const mod = await import('d3');
        d3Instance = mod;
    }
    return d3Instance;
};
