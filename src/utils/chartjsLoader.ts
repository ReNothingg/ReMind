let chartInstance = null;

export const getChart = async () => {
    if (!chartInstance) {
        const mod = await import('chart.js/auto');
        chartInstance = mod.Chart || mod.default || mod;
    }
    return chartInstance;
};
