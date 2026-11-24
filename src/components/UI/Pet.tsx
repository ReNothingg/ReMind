import { cn } from '../../utils/cn';

const petFiles = {
  idle: 'idle.svg',
  attentive: 'attentive.svg',
  typing: 'typing.svg',
  sleeping: 'sleeping.svg',
  surprised: 'surprised.svg',
  waiting: 'waiting.svg',
  thinking: 'thinking.svg',
  searching: 'searching.svg',
  working: 'working.svg',
  planning: 'attentive.svg',
  learning: 'thinking.svg',
  presenting: 'working.svg',
  coding: 'coding.svg',
  review: 'review.svg',
  paused: 'paused.svg',
  success: 'success.svg',
  error: 'error.svg',
  content: 'content.svg',
} as const;

export type PetState = keyof typeof petFiles;

export default function Pet({
  state = 'idle',
  animate = true,
  className,
}: {
  state?: PetState;
  animate?: boolean;
  className?: string;
}) {
  const src = `/assets/pet/${petFiles[state]}`;
  const still = `${src}#still`;

  return (
    <picture className={cn('ui-pet', className)} aria-hidden="true" data-pet-state={state}>
      {animate && <source media="(prefers-reduced-motion: reduce)" srcSet={still} />}
      <img src={animate ? src : still} alt="" width={28} height={28} />
    </picture>
  );
}
