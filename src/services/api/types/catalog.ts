import type { components } from "../../../generated/openapi";

export type ModelStage = 'release' | 'beta' | 'dev' | 'alpha';

export type ThinkingLevel = 'minimal' | 'low' | 'medium' | 'high';

export type ModelOption = {
    id: string;
    title: string;
    subtitle: string;
    stage?: ModelStage | string | null;
    titleKey?: string | null;
    subtitleKey?: string | null;
    thinkingLevels?: ThinkingLevel[] | string[] | null;
    defaultThinkingLevel?: ThinkingLevel | string | null;
};

export type ComposerToolOption = components['schemas']['ComposerToolEntry'];

export type ModelListResponse = components['schemas']['ModelCatalogResponse'];
