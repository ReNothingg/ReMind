import { useEffect, useState } from 'react';
import type { components } from '../../generated/openapi';
import { fetchApi } from '../../services/api/transport';
import type { RailSource } from './railPreferences';

type SearchResult = components['schemas']['SidebarSessionSearch'];

export function useSidebarSearch(owner: string | number | undefined, query: string, source: RailSource) {
  const key = owner && query ? JSON.stringify([owner, query, source]) : '';
  const [result, setResult] = useState<{ key: string; value: SearchResult | null }>();

  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ q: query, source });
    const timer = window.setTimeout(() => {
      fetchApi<SearchResult>(`/api/sidebar/session-search?${params}`, { signal: controller.signal })
        .then((value) => {
          if (!controller.signal.aborted) setResult({ key, value });
        })
        .catch(() => {
          if (!controller.signal.aborted) setResult({ key, value: null });
        });
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [key, query, source]);

  const current = key && result?.key === key ? result : undefined;
  return { results: current?.value?.sessions, partial: current?.value?.partial, loading: Boolean(key && !current), failed: current?.value === null };
}
