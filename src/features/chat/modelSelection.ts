import type { ModelOption, ModelStage, ThinkingLevel } from '../../services/api';

export const THINKING_LEVELS: ThinkingLevel[] = ['minimal', 'low', 'medium', 'high'];
const VALID_THINKING_LEVELS = new Set<ThinkingLevel>(THINKING_LEVELS);

export type ChatModel = {
    id: string;
    title: string;
    subtitle: string;
    stage: ModelStage;
    titleKey?: string;
    subtitleKey?: string;
    thinkingLevels: ThinkingLevel[];
    defaultThinkingLevel?: ThinkingLevel;
};

export const FALLBACK_MODELS: ChatModel[] = [];

const VALID_STAGES = new Set<ModelStage>(['release', 'beta', 'dev', 'alpha']);
const STAGE_LABELS: Partial<Record<ModelStage, string>> = {
    alpha: 'Alpha',
    beta: 'Beta',
    dev: 'Dev',
};

function normalizeStage(stage: ModelOption['stage']): ModelStage {
    return typeof stage === 'string' && VALID_STAGES.has(stage as ModelStage)
        ? (stage as ModelStage)
        : 'release';
}

function normalizeModel(model: ModelOption): ChatModel | null {
    const id = String(model.id || '').trim();
    if (!id) {
        return null;
    }

    const titleKey = String(model.titleKey || '').trim();
    const subtitleKey = String(model.subtitleKey || '').trim();
    const thinkingLevels = Array.isArray(model.thinkingLevels)
        ? model.thinkingLevels
            .map((level) => String(level || '').trim().toLowerCase())
            .filter((level): level is ThinkingLevel => (
                VALID_THINKING_LEVELS.has(level as ThinkingLevel)
            ))
        : [];
    const requestedDefault = String(model.defaultThinkingLevel || '').trim().toLowerCase();
    const defaultThinkingLevel = thinkingLevels.includes(requestedDefault as ThinkingLevel)
        ? requestedDefault as ThinkingLevel
        : thinkingLevels[0];

    return {
        id,
        title: String(model.title || id).trim() || id,
        subtitle: String(model.subtitle || '').trim(),
        stage: normalizeStage(model.stage),
        thinkingLevels,
        ...(titleKey ? { titleKey } : {}),
        ...(subtitleKey ? { subtitleKey } : {}),
        ...(defaultThinkingLevel ? { defaultThinkingLevel } : {}),
    };
}

export function normalizeModelOptions(models: ModelOption[]): ChatModel[] {
    const normalized = models
        .map(normalizeModel)
        .filter((model): model is ChatModel => model !== null);

    return normalized;
}

export function getModelStageLabel(stage: ModelStage): string | undefined {
    return STAGE_LABELS[stage];
}

export function isModelAvailable(modelId: string, models: ChatModel[]): boolean {
    return models.some((model) => model.id === modelId);
}

export function normalizeThinkingLevel(
    value: unknown,
    fallback: ThinkingLevel = 'medium',
): ThinkingLevel {
    const normalized = String(value || '').trim().toLowerCase();
    return VALID_THINKING_LEVELS.has(normalized as ThinkingLevel)
        ? normalized as ThinkingLevel
        : fallback;
}

export function getFallbackModelId(models: ChatModel[]): string {
    return models[0]?.id ?? '';
}
