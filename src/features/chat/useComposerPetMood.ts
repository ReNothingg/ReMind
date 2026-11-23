import { type RefObject, useEffect, useState } from 'react';

type AwakeMood = 'idle' | 'attentive' | 'typing';
type ComposerMood = AwakeMood | 'content' | 'sleeping' | 'surprised';

const RELAX_AFTER = 15_000;
const SLEEP_AFTER = 45_000;
const TYPING_PAUSE = 650;
const WAKE_DURATION = 650;

export function useComposerPetMood(
  enabled: boolean,
  composerRef: RefObject<HTMLElement | null>,
  sessionId: string | null
): ComposerMood {
  const [mood, setMood] = useState<ComposerMood>('idle');

  useEffect(() => {
    const composer = composerRef.current;
    if (!enabled || !composer) return;

    let phase: ComposerMood = 'idle';
    let afterWake: AwakeMood = 'idle';
    let relaxTimer = 0;
    let sleepTimer = 0;
    let movementTimer = 0;

    const show = (next: ComposerMood) => {
      phase = next;
      setMood(next);
    };
    const isEditor = (target: EventTarget | null) =>
      target instanceof Element && composer.contains(target) && !!target.closest('.composer-editor');
    const focusedMood = () => (isEditor(document.activeElement) ? 'attentive' : 'idle');
    const resetInactivity = () => {
      window.clearTimeout(relaxTimer);
      window.clearTimeout(sleepTimer);
      relaxTimer = window.setTimeout(() => show('content'), RELAX_AFTER);
      sleepTimer = window.setTimeout(() => show('sleeping'), SLEEP_AFTER);
    };
    const move = (next: AwakeMood) => {
      window.clearTimeout(movementTimer);
      show(next);
      if (next === 'typing') {
        movementTimer = window.setTimeout(() => show(focusedMood()), TYPING_PAUSE);
      }
    };
    const interact = (intent?: AwakeMood) => {
      if (document.hidden) return;
      resetInactivity();
      if (phase === 'sleeping') {
        afterWake = intent ?? focusedMood();
        show('surprised');
        movementTimer = window.setTimeout(() => move(afterWake), WAKE_DURATION);
      } else if (phase === 'surprised') {
        if (intent) afterWake = intent;
      } else if (intent || phase === 'content') {
        move(intent ?? focusedMood());
      }
    };
    const onActivity = () => interact();
    const onFocus = (event: FocusEvent) => {
      if (isEditor(event.target)) interact('attentive');
    };
    const onBlur = (event: FocusEvent) => {
      if (isEditor(event.target) && !isEditor(event.relatedTarget)) interact('idle');
    };
    const onInput = (event: Event) => {
      if (isEditor(event.target)) interact('typing');
    };
    const clearTimers = () => {
      window.clearTimeout(relaxTimer);
      window.clearTimeout(sleepTimer);
      window.clearTimeout(movementTimer);
    };
    const onVisibility = () => {
      if (document.hidden) {
        clearTimers();
        show('sleeping');
      } else {
        interact();
      }
    };

    const start = window.setTimeout(() => {
      if (document.hidden) show('sleeping');
      else if (phase === 'idle') move(focusedMood());
    }, 0);
    if (!document.hidden) resetInactivity();
    window.addEventListener('pointerdown', onActivity, { passive: true });
    window.addEventListener('keydown', onActivity);
    window.addEventListener('scroll', onActivity, { capture: true, passive: true });
    composer.addEventListener('focusin', onFocus);
    composer.addEventListener('focusout', onBlur);
    composer.addEventListener('input', onInput);
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      window.clearTimeout(start);
      clearTimers();
      window.removeEventListener('pointerdown', onActivity);
      window.removeEventListener('keydown', onActivity);
      window.removeEventListener('scroll', onActivity, true);
      composer.removeEventListener('focusin', onFocus);
      composer.removeEventListener('focusout', onBlur);
      composer.removeEventListener('input', onInput);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [composerRef, enabled, sessionId]);

  return enabled ? mood : 'idle';
}
