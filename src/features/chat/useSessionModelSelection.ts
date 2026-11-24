import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { components } from '../../generated/openapi';
import { fetchApi, writeApiJson } from '../../services/api/transport';
import { showToast } from '../../utils/toast';

export type ChatModelPreference = components['schemas']['ChatModelPreference'];
type SelectionView = components['schemas']['ChatModelSelectionView'];

export function useSessionModelSelection(
  owner: number,
  sessionId: string | null,
  enabled: boolean,
  generationTimestamp?: number
) {
  const { t } = useTranslation();
  const [resolved, setResolved] = useState<Record<string, ChatModelPreference | null>>({});
  const writes = useRef(new Map<string, Promise<SelectionView>>());
  const latestWrite = useRef(0);
  const scope = owner && enabled && sessionId ? owner + ':' + sessionId : '';
  const endpoint = sessionId
    ? '/sessions/' + encodeURIComponent(sessionId) + '/model-selection'
    : '';

  useEffect(() => {
    if (!scope) return;
    const controller = new AbortController();
    const readVersion = latestWrite.current;
    void fetchApi<SelectionView>(endpoint, { signal: controller.signal })
      .then(({ next }) => {
        if (
          !controller.signal.aborted &&
          readVersion === latestWrite.current &&
          !writes.current.has(scope)
        ) {
          setResolved((values) => ({ ...values, [scope]: next }));
        }
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [endpoint, scope, generationTimestamp]);

  function save(choice: ChatModelPreference) {
    if (!scope) return;
    latestWrite.current += 1;
    const previous = writes.current.get(scope) ?? Promise.resolve(null);
    const request = previous
      .catch(() => null)
      .then(() =>
        writeApiJson<SelectionView>(endpoint, 'PUT', { ...choice, expected_user_id: owner })
      );
    writes.current.set(scope, request);
    return request
      .then(
        ({ next }) => {
          if (writes.current.get(scope) === request)
            setResolved((values) => ({ ...values, [scope]: next }));
          return true;
        },
        () => {
          if (writes.current.get(scope) === request) {
            showToast(t('agentModel.saveSelectionFailed'), { type: 'error' });
          }
          return false;
        }
      )
      .finally(() => {
        if (writes.current.get(scope) === request) writes.current.delete(scope);
      });
  }

  return { choice: resolved[scope] || null, save };
}
