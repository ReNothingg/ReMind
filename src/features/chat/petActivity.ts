import type { PetState } from '../../components/UI/Pet';
import { isActiveWebSearchStatus } from '../../components/Chat/webSearchStatus';
import {
  parseThoughtTimeline,
  type ThoughtTimelineItem,
} from '../../components/Widgets/thoughtTimeline';

const petStatusLabels: Partial<Record<PetState, string>> = {
  waiting: 'composer.statusWaiting',
  thinking: 'think.label',
  searching: 'webSearch.status.started',
  working: 'think.presentation.working',
  coding: 'think.presentation.writingCode',
  review: 'toolPanels.questions',
  paused: 'chat.generationStopped',
  success: 'rail.statusComplete',
  error: 'chat.generationFailed',
  content: 'think.presentation.states.complete',
};

export function getPetStatusLabel(state: PetState): string | undefined {
  return petStatusLabels[state];
}

type PetReply = {
  content?: string;
  thinking?: { content?: string; status?: string } | null;
};

export type PetMessage = PetReply & {
  role?: string;
  isLoading?: boolean;
  isGeneratingImage?: boolean;
  isError?: boolean;
  webSearchStatus?: { status?: string } | null;
  deliveryState?: string;
  currentVariantIndex?: number;
  variants?: (PetReply & { deliveryState?: string })[];
};

export type ChatGenerationOutcome = {
  sessionId: string;
  status: 'complete' | 'error' | 'stopped';
  finishedAt: number;
};

function getPetReply(message: PetMessage) {
  return message.variants?.[message.currentVariantIndex ?? -1] ?? message;
}

function getToolPetState(item: ThoughtTimelineItem): PetState {
  switch (item.kind) {
    case 'thought':
      return 'thinking';
    case 'search':
      return 'searching';
    case 'model':
      return 'waiting';
    case 'python':
      return 'coding';
    case 'tool':
      if (item.name === 'ask_user' || item.name === 'plan_update') return 'review';
      if (item.name === 'python_execute') return 'coding';
      if (item.name.startsWith('web_')) return 'searching';
  }
  return 'working';
}

function hasOpenCodeFence(content: string): boolean {
  let fence = '';
  for (const [, marker = '', info = ''] of content.matchAll(/^ {0,3}(`{3,}|~{3,})([^\r\n]*)/gm)) {
    if (fence) {
      if (fence[0] === marker[0] && marker.length >= fence.length && !info.trim()) fence = '';
    } else if (marker[0] === '~' || !info.includes('`')) {
      fence = marker;
    }
  }
  return Boolean(fence);
}

export function getActivePetState(message?: PetMessage, canvasType?: string): PetState {
  if (canvasType) return canvasType.startsWith('code/') ? 'coding' : 'working';
  if (!message) return 'waiting';
  if (isActiveWebSearchStatus(message.webSearchStatus?.status)) return 'searching';
  if (message.isGeneratingImage) return 'working';

  const reply = getPetReply(message);
  const content = reply.content ?? '';
  if (hasOpenCodeFence(content)) return 'coding';

  const thinking = reply.thinking ?? message.thinking;
  if (thinking?.status === 'streaming') {
    const item = parseThoughtTimeline(thinking.content ?? '').at(-1);
    if (!item) return 'thinking';
    if (item.kind === 'thought' || item.status === 'running' || item.status.endsWith('_running')) {
      return getToolPetState(item);
    }
    if (item.kind === 'model' && item.status === 'model_waiting') return 'waiting';
    if (item.kind === 'search' && isActiveWebSearchStatus(item.status)) return 'searching';
    return 'thinking';
  }

  return content.trim() || thinking?.status === 'complete' ? 'working' : 'waiting';
}
