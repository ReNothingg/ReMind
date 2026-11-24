import { useTranslation } from 'react-i18next';
import type { ThinkingLevel } from '../../services/api';
import type { ProviderModel } from './providerModelContract';

type EffortOption = NonNullable<ProviderModel['reasoningEfforts']>;
type Capacity = 'contextWindow' | 'maxTokens';

const capacityFields: ReadonlyArray<{ key: Capacity; max: number }> = [
  { key: 'contextWindow', max: 16000000 },
  { key: 'maxTokens', max: 262144 },
];

export default function ProviderModelSettings({
  model,
  levels,
  editableWire,
  disabled,
  onChange,
}: {
  model: ProviderModel;
  levels: ThinkingLevel[];
  editableWire: boolean;
  disabled: boolean;
  onChange: (model: ProviderModel) => void;
}) {
  const { t } = useTranslation();
  const efforts = typeof model.reasoningEfforts === 'object' ? model.reasoningEfforts : undefined;

  function setCapacity(key: Capacity, value: string) {
    const next = { ...model };
    if (value) next[key] = Number(value);
    else delete next[key];
    onChange(next);
  }

  function setEfforts(value: EffortOption | undefined) {
    const next = { ...model };
    if (value === undefined) delete next.reasoningEfforts;
    else next.reasoningEfforts = value;
    onChange(next);
  }

  function toggleLevel(level: ThinkingLevel, enabled: boolean) {
    const next = { ...efforts };
    if (!enabled) delete next[level];
    else if (level === 'none') next.none = null;
    else next[level] = level;
    setEfforts(next);
  }

  return (
    <details className="agent-provider-model-details">
      <summary aria-label={t('agentModel.settingsFor', { name: model.title })}>
        <span>{model.title}</span>
        <code>{model.slug}</code>
      </summary>
      <fieldset disabled={disabled} className="agent-provider-model-fields">
        <label>
          <span>{t('agentSettings.modelDisplayName')}</span>
          <input
            required
            maxLength={160}
            value={model.title}
            onChange={(event) => {
              onChange({ ...model, title: event.target.value });
            }}
          />
        </label>
        <div className="agent-provider-model-capacity">
          {capacityFields.map(({ key, max }) => (
            <label key={key}>
              <span>{t('agentModel.' + key)}</span>
              <input
                type="number"
                value={model[key] ?? ''}
                min={1}
                max={
                  key === 'maxTokens' && model.contextWindow
                    ? Math.min(max, model.contextWindow - 1)
                    : max
                }
                placeholder={t('agentModel.inherit')}
                onChange={(event) => setCapacity(key, event.target.value)}
              />
            </label>
          ))}
        </div>
        <label>
          <span>{t('agentModel.inputs')}</span>
          <select
            value={
              model.inputModalities?.includes('image')
                ? 'image'
                : model.inputModalities
                  ? 'text'
                  : ''
            }
            onChange={(event) => {
              const next = { ...model };
              if (!event.target.value) delete next.inputModalities;
              else
                next.inputModalities =
                  event.target.value === 'image' ? ['text', 'image'] : ['text'];
              onChange(next);
            }}
          >
            <option value="">{t('agentModel.inherit')}</option>
            <option value="text">{t('agentModel.text')}</option>
            <option value="image">{t('agentModel.textImages')}</option>
          </select>
        </label>
        <label>
          <span>{t('models.thinkingLevel')}</span>
          <select
            value={efforts ? 'custom' : model.reasoningEfforts === false ? 'hidden' : ''}
            onChange={(event) => {
              if (event.target.value === 'custom') {
                const initial = levels.filter((level) => ['low', 'medium', 'high'].includes(level));
                setEfforts(Object.fromEntries(initial.map((level) => [level, level])));
              } else setEfforts(event.target.value === 'hidden' ? false : undefined);
            }}
          >
            <option value="">{t('agentModel.inherit')}</option>
            <option value="hidden">{t('agentModel.hideEffort')}</option>
            <option value="custom">{t('agentModel.customEffort')}</option>
          </select>
        </label>
        {efforts && (
          <fieldset className="agent-provider-model-efforts">
            <legend>{t('agentModel.effortLevels')}</legend>
            {levels.map((level) => (
              <div key={level}>
                <label className="agent-checkbox">
                  <input
                    type="checkbox"
                    checked={Object.hasOwn(efforts, level)}
                    disabled={Object.keys(efforts).length === 1 && Object.hasOwn(efforts, level)}
                    onChange={(event) => toggleLevel(level, event.target.checked)}
                  />
                  {t('models.thinkingLevels.' + level)}
                </label>
                {editableWire && Object.hasOwn(efforts, level) && (
                  <input
                    aria-label={t('agentModel.wireFor', {
                      level: t('models.thinkingLevels.' + level),
                    })}
                    value={efforts[level] ?? ''}
                    placeholder={level === 'none' ? t('agentModel.inherit') : level}
                    pattern="[A-Za-z0-9](?:[A-Za-z0-9_]|-){0,31}"
                    maxLength={32}
                    required={level !== 'none'}
                    onChange={(event) =>
                      setEfforts({ ...efforts, [level]: event.target.value || null })
                    }
                  />
                )}
              </div>
            ))}
          </fieldset>
        )}
      </fieldset>
    </details>
  );
}
