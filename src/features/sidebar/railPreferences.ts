import { useMemo, useState } from 'react';

export const railPanels = ['plugins', 'automations', 'minds', 'admin'] as const;
export type RailPanelId = (typeof railPanels)[number];
export type RailGrouping = 'projects' | 'flat';
export type RailOrder = 'recent' | 'alphabetical';
export type RailSource = 'all' | 'web' | 'telegram';

type Preferences = {
  unpinned: RailPanelId[];
  grouping: RailGrouping;
  order: RailOrder;
  source: RailSource;
};

const defaults: Preferences = {
  unpinned: ['minds', 'admin'],
  grouping: 'projects',
  order: 'recent',
  source: 'all',
};

function read(key: string): Preferences {
  try {
    const saved = JSON.parse(localStorage.getItem(key) || 'null');
    if (!saved || typeof saved !== 'object') return defaults;
    return {
      unpinned: Array.isArray(saved.unpinned)
        ? railPanels.filter((id) => saved.unpinned.includes(id))
        : defaults.unpinned,
      grouping: saved.grouping === 'flat' ? 'flat' : 'projects',
      order: saved.order === 'alphabetical' ? 'alphabetical' : 'recent',
      source: saved.source === 'web' || saved.source === 'telegram' ? saved.source : 'all',
    };
  } catch {
    return defaults;
  }
}

export function useRailPreferences(owner: string | number | undefined) {
  const key = `remind:sidebar:${owner ?? 'guest'}`;
  const persisted = useMemo(() => read(key), [key]);
  const [draft, setDraft] = useState<{ key: string; value: Preferences }>();
  const preferences = draft?.key === key ? draft.value : persisted;

  function update(patch: Partial<Preferences>) {
    const value = { ...preferences, ...patch };
    setDraft({ key, value });
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      return;
    }
  }

  return { preferences, update };
}
