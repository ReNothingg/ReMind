import type { ModelOption, ModelSpeed, ModelStage, ThinkingLevel } from '../../services/api';

export const THINKING_LEVELS: ThinkingLevel[] = [
  'none',
  'minimal',
  'low',
  'medium',
  'high',
  'xhigh',
  'max',
  'ultra',
];
const VALID_THINKING_LEVELS = new Set<ThinkingLevel>(THINKING_LEVELS);

export type ChatModel = {
  id: string;
  title: string;
  subtitle: string;
  source: string;
  provider: string;
  serviceTiers: ModelSpeed[];
  stage: ModelStage;
  titleKey?: string;
  subtitleKey?: string;
  thinkingLevels: ThinkingLevel[];
  defaultThinkingLevel?: ThinkingLevel;
  availableUntil?: string;
  contextWindow?: number;
  maxTokens?: number;
  inputModalities?: Array<'text' | 'image'>;
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
  const availableUntil = String(model.availableUntil || '').trim();
  const thinkingLevels = Array.isArray(model.thinkingLevels)
    ? model.thinkingLevels
        .map((level) =>
          String(level || '')
            .trim()
            .toLowerCase()
        )
        .filter((level): level is ThinkingLevel =>
          VALID_THINKING_LEVELS.has(level as ThinkingLevel)
        )
    : [];
  const requestedDefault = String(model.defaultThinkingLevel || '')
    .trim()
    .toLowerCase();
  const defaultThinkingLevel = thinkingLevels.includes(requestedDefault as ThinkingLevel)
    ? (requestedDefault as ThinkingLevel)
    : thinkingLevels[0];

  return {
    id,
    title: String(model.title || id).trim() || id,
    subtitle: String(model.subtitle || '').trim(),
    stage: normalizeStage(model.stage),
    source: model.source || 'platform',
    provider: model.provider || '',
    serviceTiers: [
      'standard',
      ...(['fast', 'ultrafast'] as const).filter((speed) => model.serviceTiers?.includes(speed)),
    ],
    thinkingLevels,
    ...(titleKey ? { titleKey } : {}),
    ...(subtitleKey ? { subtitleKey } : {}),
    ...(defaultThinkingLevel ? { defaultThinkingLevel } : {}),
    ...(typeof model.contextWindow === 'number' && model.contextWindow > 0 ? { contextWindow: model.contextWindow } : {}),
    ...(typeof model.maxTokens === 'number' && model.maxTokens > 0 ? { maxTokens: model.maxTokens } : {}),
    ...(Array.isArray(model.inputModalities) ? { inputModalities: model.inputModalities } : {}),
    ...(/^\d{4}-\d{2}-\d{2}$/.test(availableUntil) ? { availableUntil } : {}),
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
  fallback: ThinkingLevel = 'medium'
): ThinkingLevel {
  const normalized = String(value || '')
    .trim()
    .toLowerCase();
  return VALID_THINKING_LEVELS.has(normalized as ThinkingLevel)
    ? (normalized as ThinkingLevel)
    : fallback;
}

export function getFallbackModelId(models: ChatModel[]): string {
  return models[0]?.id ?? '';
}

export function isImageToolModel(model: Pick<ChatModel, 'id'>): boolean {
  return model.id === 'demo_image' || model.id === 'mindart';
}
