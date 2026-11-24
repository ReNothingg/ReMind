import type { TFunction } from 'i18next';
import {
  Accessibility, Cog, Info, LayoutPanelLeft, Palette, Send, ShieldCheck,
  SlidersHorizontal, UserRound, Waypoints, type LucideIcon,
} from 'lucide-react';

export type SettingsSectionId = 'account' | 'models' | 'workspace' | 'telegram' | 'appearance' |
  'personalization' | 'interface' | 'accessibility' | 'privacy' | 'about';

export type SettingsSection = { id: SettingsSectionId; label: string; icon: LucideIcon };
export type SettingsSectionGroup = { id: string; label?: string; rows: SettingsSection[] };

export function settingsSectionGroups(t: TFunction, authenticated: boolean): SettingsSectionGroup[] {
  const work: SettingsSectionGroup[] = authenticated ? [{
    id: 'work',
    label: t('settings.navigation.work'),
    rows: [
      { id: 'models', label: t('agentSettings.title'), icon: Waypoints },
      { id: 'workspace', label: t('workspace.title'), icon: Cog },
      { id: 'telegram', label: t('agentTelegram.title'), icon: Send },
    ],
  }] : [];

  return [
    { id: 'account', rows: [{ id: 'account', label: t('settings.tabs.account'), icon: UserRound }] },
    ...work,
    {
      id: 'application',
      label: t('settings.navigation.application'),
      rows: [
        { id: 'appearance', label: t('settings.tabs.appearance'), icon: Palette },
        ...(authenticated ? [{
          id: 'personalization' as const,
          label: t('settings.tabs.personalization'),
          icon: SlidersHorizontal,
        }] : []),
        { id: 'interface', label: t('settings.tabs.interface'), icon: LayoutPanelLeft },
        { id: 'accessibility', label: t('settings.tabs.accessibility'), icon: Accessibility },
      ],
    },
    {
      id: 'data',
      label: t('settings.navigation.data'),
      rows: [
        { id: 'privacy', label: t('settings.tabs.privacy'), icon: ShieldCheck },
        { id: 'about', label: t('settings.tabs.about'), icon: Info },
      ],
    },
  ];
}
