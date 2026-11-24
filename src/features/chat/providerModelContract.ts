import type { components } from '../../generated/openapi';
import type { ThinkingLevel } from '../../services/api';
import { THINKING_LEVELS } from './modelSelection';

export type ProviderModel = components['schemas']['AgentProviderModel'];
export type ProviderRetryPolicy = components['schemas']['ProviderRetryPolicy'];

export const defaultRetryPolicy: ProviderRetryPolicy = {
  mode: 'normal',
  maxRetries: 5,
  retryableCodes: ['EMPTY_RESPONSE', 'RATE_LIMIT', 'SERVER', 'TIMEOUT', 'TRANSPORT'],
  backoff: { initialDelayMs: 500, maxDelayMs: 10000, jitterRatio: 0.1 },
};

export function modelReasoningLevels(provider: string, protocol: string): ThinkingLevel[] {
  if (provider === 'deepseek') return ['none', 'low', 'high', 'max'];
  if (protocol === 'google-generative-ai') return ['minimal', 'low', 'medium', 'high'];
  if (protocol === 'anthropic-messages') return ['low', 'medium', 'high', 'xhigh', 'max'];
  return THINKING_LEVELS;
}
