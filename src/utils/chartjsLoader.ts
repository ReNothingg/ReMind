type ChartConstructor = typeof import('chart.js/auto').Chart;

let chartInstance: ChartConstructor | null = null;

export const getChart = async () => {
    if (!chartInstance) {
        const { Chart } = await import('chart.js/auto');
        chartInstance = Chart;
    }
    return chartInstance;
};
