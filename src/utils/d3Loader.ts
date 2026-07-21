type D3Module = typeof import('d3');

let d3Instance: D3Module | null = null;

export const getD3 = async () => {
    if (!d3Instance) {
        const mod = await import('d3');
        d3Instance = mod;
    }
    return d3Instance;
};
