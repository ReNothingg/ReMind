import { useTranslation } from 'react-i18next';
import { defaultRetryPolicy, type ProviderRetryPolicy } from './providerModelContract';

export default function ProviderRetrySettings({
  value,
  onChange,
  disabled,
}: {
  value: ProviderRetryPolicy;
  onChange: (policy: ProviderRetryPolicy) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const updateDelay = (name: keyof ProviderRetryPolicy['backoff'], amount: number) =>
    onChange({ ...value, backoff: { ...value.backoff, [name]: amount } });
  return (
    <details className="agent-advanced-settings">
      <summary>{t('agentRetry.title')}</summary>
      <fieldset disabled={disabled}>
        <p>{t('agentRetry.hint')}</p>
        <label>
          {t('agentRetry.mode')}
          <select
            value={value.mode}
            onChange={(event) =>
              onChange({ ...value, mode: event.target.value === 'always' ? 'always' : 'normal' })
            }
          >
            <option value="normal">{t('agentRetry.normal')}</option>
            <option value="always">{t('agentRetry.always')}</option>
          </select>
        </label>
        {value.mode === 'normal' && (
          <>
            <label>
              {t('agentRetry.maxRetries')}
              <input
                type="number"
                required
                min={0}
                max={8}
                value={Number.isFinite(value.maxRetries) ? value.maxRetries : ''}
                onChange={(event) => onChange({ ...value, maxRetries: event.target.valueAsNumber })}
              />
            </label>
            <div className="agent-retry-codes" role="group" aria-label={t('agentRetry.codes')}>
              {defaultRetryPolicy.retryableCodes.map((code) => (
                <label key={code}>
                  <input
                    type="checkbox"
                    checked={value.retryableCodes.includes(code)}
                    disabled={value.retryableCodes.length === 1 && value.retryableCodes[0] === code}
                    onChange={(event) =>
                      onChange({
                        ...value,
                        retryableCodes: event.target.checked
                          ? [...value.retryableCodes, code]
                          : value.retryableCodes.filter((value) => value !== code),
                      })
                    }
                  />
                  {t('agentRetry.errors.' + code)}
                </label>
              ))}
            </div>
          </>
        )}
        {(['initialDelayMs', 'maxDelayMs', 'jitterRatio'] as const).map((field) => (
          <label key={field}>
            {t('agentRetry.' + field)}
            <input
              type="number"
              required
              min={field === 'jitterRatio' ? 0 : 100}
              max={
                field === 'jitterRatio'
                  ? 1
                  : field === 'initialDelayMs' && Number.isFinite(value.backoff.maxDelayMs)
                    ? value.backoff.maxDelayMs
                    : 15000
              }
              step={field === 'jitterRatio' ? 0.01 : 1}
              value={Number.isFinite(value.backoff[field]) ? value.backoff[field] : ''}
              onChange={(event) => updateDelay(field, event.target.valueAsNumber)}
            />
          </label>
        ))}
        <button type="button" onClick={() => onChange(defaultRetryPolicy)}>
          {t('workspace.restoreDefaults')}
        </button>
      </fieldset>
    </details>
  );
}
