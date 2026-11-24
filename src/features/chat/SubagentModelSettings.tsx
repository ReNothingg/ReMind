import { useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { indexModelCatalog } from './modelCatalogSearch';
import type { ChatModel } from './modelSelection';

const maxModels = 24;
const scope = 'agentExecution.subagentRoutes.';
type CatalogStatus = 'loading' | 'ready' | 'error';

export default function SubagentModelSettings({
  enabled,
  selected,
  models,
  status,
  retry,
  onEnable,
  onSelect,
}: {
  enabled: boolean;
  selected: string[];
  models: ChatModel[];
  status: CatalogStatus;
  retry: () => void;
  onEnable: (enabled: boolean) => void;
  onSelect: (models: string[]) => void;
}) {
  const { t } = useTranslation();
  const groupTitle = useId();
  const [query, setQuery] = useState('');
  const catalog = useMemo(() => {
    const entries = models.map((model) => ({
      id: model.id,
      title: model.titleKey ? t(model.titleKey, { defaultValue: model.title }) : model.title,
      source: model.source === 'key' && model.subtitle
        ? model.subtitle
        : t('agentSettings.sources.' + model.source, { defaultValue: model.source }),
    }));
    return indexModelCatalog(entries, ({ id, title, source }) => ({ names: [title, id], descriptions: [source] }));
  }, [models, t]);
  const groups = new Map<string, ReturnType<typeof catalog>[number][]>();
  for (const option of catalog(query)) {
    const group = groups.get(option.source) ?? [];
    group.push(option);
    groups.set(option.source, group);
  }
  const known = new Set(models.map(({ id }) => id));
  const unavailable = status === 'ready' ? selected.filter((id) => !known.has(id)) : [];
  const atLimit = selected.length >= maxModels;

  function toggle(id: string) {
    if (selected.includes(id)) onSelect(selected.filter((entry) => entry !== id));
    else if (!atLimit) onSelect([...selected, id]);
  }

  return (
    <div className="agent-subagent-models">
      <label className="agent-tool-settings-check">
        <input type="checkbox" checked={enabled} onChange={(event) => onEnable(event.target.checked)} />
        <span>{t(scope + 'enable')}</span>
      </label>
      {enabled && (
        <div className="agent-subagent-catalog" role="group" aria-labelledby={groupTitle}>
          <p>{t(scope + 'hint')}</p>
          <div className="agent-subagent-catalog-heading">
            <h3 id={groupTitle}>{t(scope + 'title')}</h3>
            <span>{t(scope + 'count', { selected: selected.length, max: maxModels })}</span>
          </div>
          {status === 'loading' && <p role="status">{t('agentExecution.loading')}</p>}
          {status === 'error' && (
            <div role="alert" className="native-workspace-links">
              <p>{t(scope + 'loadFailed')}</p>
              <button type="button" onClick={retry}>{t('agentWeb.reload')}</button>
            </div>
          )}
          {status === 'ready' && (
            <>
              {models.length > 4 && (
                <input
                  type="search"
                  aria-label={t(scope + 'search')}
                  placeholder={t(scope + 'search')}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              )}
              <div className="agent-subagent-model-list">
                {[...groups].map(([source, entries]) => (
                  <div key={source} role="group" aria-label={source}>
                    <p>{source}</p>
                    {entries.map(({ id, title }) => (
                      <label key={id} className="agent-tool-settings-check">
                        <input type="checkbox" checked={selected.includes(id)} disabled={atLimit && !selected.includes(id)} onChange={() => toggle(id)} />
                        <span>{title}</span>
                      </label>
                    ))}
                  </div>
                ))}
                {groups.size === 0 && <p>{t(scope + 'empty')}</p>}
                {unavailable.length > 0 && (
                  <div role="group" aria-label={t('agentSettings.modelUnavailable')}>
                    <p>{t('agentSettings.modelUnavailable')}</p>
                    {unavailable.map((id) => (
                      <label key={id} className="agent-tool-settings-check">
                        <input type="checkbox" checked onChange={() => toggle(id)} />
                        <span>{id}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
          {!selected.length && <p>{t(scope + 'required')}</p>}
        </div>
      )}
    </div>
  );
}
