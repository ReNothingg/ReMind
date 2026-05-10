import type { AuthUser } from '../../services/auth';

export type ModelStage = 'release' | 'beta' | 'dev' | 'alpha';

export interface ModelDefinition {
    id: string;
    name: string;
    descKey: string;
    descFallback: string;
    stage: ModelStage;
}

export const MODEL_DEFINITIONS: ModelDefinition[] = [
    {
        id: 'gemini',
        name: 'Gemini',
        descKey: 'models.gemini.desc',
        descFallback: 'General-purpose Google model',
        stage: 'release',
    },
    {
        id: 'demo_image',
        name: 'Mind image',
        descKey: 'models.demoImage.desc',
        descFallback: 'Image generation model in development',
        stage: 'dev',
    },
    {
        id: 'echo',
        name: 'Echo',
        descKey: 'models.echo.desc',
        descFallback: 'Echo bot for testing',
        stage: 'dev',
    },
];

const BETA_PERCENT = 50;
const STAGE_LABELS: Partial<Record<ModelStage, string>> = {
    alpha: 'Alpha',
    beta: 'Beta',
    dev: 'Dev',
};

function stableBucket(modelId: string, userId: number): number {
    const value = `${modelId.trim().toLowerCase()}:${userId}`;
    let hash = 2166136261;
    for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619) >>> 0;
    }
    return hash % 100;
}

export function getModelStageLabel(stage: ModelStage): string | undefined {
    return STAGE_LABELS[stage];
}

export function canUseModel(model: ModelDefinition, user: AuthUser | null): boolean {
    if (model.stage === 'release') {
        return true;
    }

    const isAdmin = !!user?.is_admin || !!user?.is_super_admin;
    if (model.stage === 'dev' || model.stage === 'alpha') {
        return isAdmin;
    }

    if (model.stage === 'beta') {
        return !!user && stableBucket(model.id, user.id) < BETA_PERCENT;
    }

    return false;
}

export function getAvailableModels(user: AuthUser | null): ModelDefinition[] {
    return MODEL_DEFINITIONS.filter((model) => canUseModel(model, user));
}

export function isModelAvailable(modelId: string, user: AuthUser | null): boolean {
    const model = MODEL_DEFINITIONS.find((entry) => entry.id === modelId);
    return !!model && canUseModel(model, user);
}

export function getFallbackModelId(user: AuthUser | null): string {
    return getAvailableModels(user)[0]?.id ?? 'gemini';
}
