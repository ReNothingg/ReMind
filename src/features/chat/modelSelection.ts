import type { ModelOption, ModelStage } from '../../services/api';

export type ChatModel = {
    id: string;
    title: string;
    subtitle: string;
    stage: ModelStage;
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

    return {
        id,
        title: String(model.title || id).trim() || id,
        subtitle: String(model.subtitle || '').trim(),
        stage: normalizeStage(model.stage),
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

export function getFallbackModelId(models: ChatModel[]): string {
    return models[0]?.id ?? '';
}
