import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ExternalLink, RefreshCw } from 'lucide-react';
import { fetchApi } from '../../services/api/transport';

type Limit = { usedPercent: number; windowDurationMins?: number; resetsAt?: number };
type Status = {
  configured: boolean;
  connected: boolean;
  loginState?: string;
  email?: string;
  plan?: string;
  limits?: { name?: string; primary?: Limit; secondary?: Limit }[];
};
type Login = { url: string; code: string };

function usageDuration(minutes: number, language: string) {
  const unit =
    minutes >= 1440 && minutes % 1440 === 0
      ? 'day'
      : minutes >= 60 && minutes % 60 === 0
        ? 'hour'
        : 'minute';
  const amount = minutes / (unit === 'day' ? 1440 : unit === 'hour' ? 60 : 1);
  return new Intl.NumberFormat(language, { style: 'unit', unit, unitDisplay: 'short' }).format(
    amount
  );
}

export default function CodexSettings() {
  const { t, i18n } = useTranslation();
  const [status, setStatus] = useState<Status | null>(null);
  const [login, setLogin] = useState<Login | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let mounted = true;
    let timer = 0;
    const read = async () => {
      try {
        const data = await fetchApi<Status>(
          '/api/agent/codex' + (login || revision ? '?refresh=1' : '')
        );
        if (!mounted) return;
        setStatus(data);
        setError(false);
        if (data.connected && login) {
          setLogin(null);
          window.dispatchEvent(new Event('remind:model-catalog'));
        } else if (login && data.loginState === 'failed') {
          setLogin(null);
          setError(true);
        } else if (login) timer = window.setTimeout(() => void read(), 5000);
      } catch {
        if (mounted) setError(true);
      }
    };
    void read();
    return () => {
      mounted = false;
      window.clearTimeout(timer);
    };
  }, [login, revision]);
  const cancel = async () => {
    try {
      await fetchApi('/api/agent/codex/cancel', { method: 'POST' });
      setLogin(null);
    } catch {
      setError(true);
    }
  };
  const update = async () => {
    setBusy(true);
    setError(false);
    try {
      if (status?.connected) {
        await fetchApi('/api/agent/codex', { method: 'DELETE' });
        setLogin(null);
        setStatus({ ...status, connected: false, limits: [] });
        window.dispatchEvent(new Event('remind:model-catalog'));
      } else {
        const fresh = await fetchApi<Login>('/api/agent/codex', { method: 'POST' });
        if (new URL(fresh.url).origin !== 'https://auth.openai.com') throw new Error();
        setLogin(fresh);
      }
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="agent-codex">
      <div className="agent-settings-title">
        <h3>{t('agentSettings.sources.codex')}</h3>
        <button
          type="button"
          aria-label={t('agentSettings.refresh', { name: 'Codex' })}
          onClick={() => setRevision((a) => a + 1)}
        >
          <RefreshCw size={16} />
        </button>
      </div>
      <p>
        {status?.connected
          ? [status.email, status.plan].filter(Boolean).join(' · ')
          : t(
              status && !status.configured
                ? 'workspace.unconfigured'
                : 'agentSettings.codexDescription'
            )}
      </p>
      {status?.configured && !login && (
        <button
          className="mind-secondary-action"
          type="button"
          disabled={busy}
          onClick={() => void update()}
        >
          {t(status.connected ? 'chatgptAccount.disconnect' : 'agentSettings.connectCodex')}
        </button>
      )}
      {login && (
        <div className="agent-device-login">
          <p>{t('agentSettings.deviceInstruction')}</p>
          <code dir="ltr">{login.code}</code>
          <a href={login.url} target="_blank" rel="noreferrer">
            {t('agentSettings.openOpenAI')} <ExternalLink size={15} />
          </a>
          <button type="button" onClick={() => void cancel()}>
            {t('common.close')}
          </button>
        </div>
      )}
      {status?.connected &&
        status.limits?.map((group, i) => (
          <div className="agent-usage" key={i}>
            {Boolean((status.limits?.length || 0) > 1 && group.name) && (
              <strong>{group.name}</strong>
            )}
            {[group.primary, group.secondary].map(
              (window, index) =>
                window && (
                  <div key={index}>
                    <span>
                      {window.windowDurationMins ? t('agentSettings.usageWindow', {
                        duration: usageDuration(window.windowDurationMins || 0, i18n.language),
                        percent: window.usedPercent,
                      }) : new Intl.NumberFormat(i18n.language,{style:'percent',maximumFractionDigits:1}).format(window.usedPercent/100)}
                    </span>
                    <progress
                      aria-label={t('chatgptAccount.usage')}
                      max={100}
                      value={window.usedPercent}
                    />
                    {Boolean(window.resetsAt) && (
                      <small>
                        {t('agentSettings.reset', {
                          date: new Date(Number(window.resetsAt) * 1000).toLocaleString(
                            i18n.language
                          ),
                        })}
                      </small>
                    )}
                  </div>
                )
            )}
          </div>
        ))}
      {error && (
        <div role="alert" className="account-connected-app-error">
          {t('agentSettings.codexFailed')}
        </div>
      )}
    </section>
  );
}
