import type { components } from '../../../generated/openapi';

export type ModelStage = 'release' | 'beta' | 'dev' | 'alpha';

export type ThinkingLevel =
  'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max' | 'none' | 'ultra';

export type ModelSpeed = 'standard' | 'fast' | 'ultrafast';

export type ModelOption = {
  source?: string;
  provider?: string;
  serviceTiers?: string[];
  id: string;
  title: string;
  subtitle: string;
  stage?: ModelStage | string | null;
  titleKey?: string | null;
  subtitleKey?: string | null;
  thinkingLevels?: ThinkingLevel[] | string[] | null;
  defaultThinkingLevel?: ThinkingLevel | string | null;
  availableUntil?: string | null;
  contextWindow?: number;
  maxTokens?: number;
  inputModalities?: Array<'text' | 'image'>;
};

export type ComposerToolOption = components['schemas']['ComposerToolEntry'];

export type ModelListResponse = components['schemas']['ModelCatalogResponse'];
