type WidgetLike = {
    type?: string;
    state?: unknown;
};

const normalizeJsonValue = (value: unknown): unknown => {
    if (Array.isArray(value)) {
        return value.map(normalizeJsonValue);
    }
    if (value && typeof value === 'object') {
        return Object.keys(value as Record<string, unknown>)
            .sort()
            .reduce<Record<string, unknown>>((normalized, key) => {
                normalized[key] = normalizeJsonValue((value as Record<string, unknown>)[key]);
                return normalized;
            }, {});
    }
    return value;
};

export const hasEquivalentWidget = (
    widgets: readonly WidgetLike[],
    type: string,
    state: unknown
): boolean => {
    const stateFingerprint = JSON.stringify(normalizeJsonValue(state));
    return widgets.some(
        (widget) =>
            widget.type === type &&
            JSON.stringify(normalizeJsonValue(widget.state)) === stateFingerprint
    );
};
