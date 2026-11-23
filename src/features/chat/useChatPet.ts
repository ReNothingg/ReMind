import { useEffect, useState } from 'react';
import type { PetState } from '../../components/UI/Pet';
import { getActivePetState, type ChatGenerationOutcome, type PetMessage } from './petActivity';

const REACTION_DURATION = 2300;
const reactions: Record<ChatGenerationOutcome['status'], PetState> = {
  complete: 'success',
  error: 'error',
  stopped: 'paused',
};

export function useChatPet(
  history: PetMessage[],
  isLoading: boolean,
  sessionId: string | null,
  outcome: ChatGenerationOutcome | null,
  canvasType?: string
): PetState {
  const [expired, setExpired] = useState<ChatGenerationOutcome | null>(null);

  useEffect(() => {
    if (!outcome) return;
    const remaining = Math.max(0, REACTION_DURATION - (Date.now() - outcome.finishedAt));
    const timer = window.setTimeout(() => setExpired(outcome), remaining);
    return () => window.clearTimeout(timer);
  }, [outcome]);

  if (isLoading) {
    return getActivePetState(
      history.findLast((message) => message.role !== 'user' && message.isLoading),
      canvasType
    );
  }
  if (outcome && outcome.sessionId === sessionId && outcome !== expired) {
    return reactions[outcome.status];
  }
  return 'idle';
}
