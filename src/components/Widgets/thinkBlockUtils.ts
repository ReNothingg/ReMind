type ThinkWidget = {
    type: string;
    id: string;
    content?: string;
    openTime?: number;
    closeTime?: number;
    [key: string]: unknown;
};

export function mergeThinkWidgets<T extends ThinkWidget>(widgets: T[], mergedId: string): T[] {
    const thoughts = widgets.filter((widget) => widget.type === 'think');
    if (thoughts.length <= 1) {
        return widgets;
    }
    const openTimes = thoughts.map((widget) => Number(widget.openTime)).filter(Number.isFinite);
    const closeTimes = thoughts.map((widget) => Number(widget.closeTime)).filter(Number.isFinite);
    const merged = {
        ...thoughts[0],
        id: mergedId,
        content: thoughts
            .map((widget) => String(widget.content || '').trim())
            .filter(Boolean)
            .join('\n\n'),
        openTime: openTimes.length > 0 ? Math.min(...openTimes) : undefined,
        closeTime: closeTimes.length > 0 ? Math.max(...closeTimes) : undefined,
    } as T;
    let inserted = false;
    return widgets.reduce<T[]>((result, widget) => {
        if (widget.type !== 'think') {
            result.push(widget);
        } else if (!inserted) {
            result.push(merged);
            inserted = true;
        }
        return result;
    }, []);
}
