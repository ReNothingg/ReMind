import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchApi } from '../../services/api/transport';
import { authService, type TelegramLinkRequest } from '../../services/auth';
import { apiService, type Mind, type ModelOption } from '../../services/api';

type Settings = {
  model: string;
  mind_id: string | null;
  serviceTier: string;
  webSearch: boolean;
  secretaryMode: string;
  linked: boolean;
  businessConnected: boolean;
  canReply: boolean;
  bot: string | null;
};
export default function TelegramAgentSettings() {
  const { t } = useTranslation();
  const [state, setState] = useState<Settings | null>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [minds, setMinds] = useState<Mind[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [saved, setSaved] = useState(false);
  const [link, setLink] = useState<TelegramLinkRequest | null>(null);
  const connect = async () => {
    setBusy(true);
    setError(false);
    try {
      const fresh = await authService.createTelegramLink();
      const url = new URL(fresh.url);
      if (url.origin !== 'https://t.me') throw new Error();
      setLink(fresh);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    if (!link) return;
    let active = true;
    let timer = 0;
    const deadline = Date.now() + link.expires_in * 1000;
    const poll = async () => {
      try {
        const answer = await authService.getTelegramLinkStatus(link.request_id);
        if (!active) return;
        if (answer.status === 'linked') {
          setState((prev) => prev && { ...prev, linked: true });
          setLink(null);
          return;
        }
        if (answer.status !== 'pending' || Date.now() >= deadline) {
          setLink(null);
          return;
        }
      } catch {
        if (!active) return;
      }
      timer = window.setTimeout(() => void poll(), 4000);
    };
    timer = window.setTimeout(() => void poll(), 2000);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [link]);
  useEffect(() => {
    let active = true;
    Promise.all([
      fetchApi<Settings>('/api/agent/telegram'),
      apiService.listModels(),
      apiService.listMinds({ mine: true }),
      apiService.listPinnedMinds(),
    ])
      .then(([data, options, owned, pinned]) => {
        if (!active) return;
        setState(data);
        setModels(options);
        setMinds(
          Array.from(
            new Map([...(owned.minds || []), ...pinned].map((m) => [m.public_id, m])).values()
          )
        );
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
  }, []);
  const change = (patch: Partial<Settings>) => {
    setSaved(false);
    setState((prev) => prev && { ...prev, ...patch });
  };
  const submit = async () => {
    if (!state) return;
    setBusy(true);
    setError(false);
    try {
      const { model, mind_id, serviceTier, webSearch, secretaryMode } = state;
      const result = await fetchApi<Settings>('/api/agent/telegram', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, mind_id, serviceTier, webSearch, secretaryMode }),
      });
      setState(result);
      setSaved(true);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };
  const selected = models.find((m) => m.id === state?.model);
  return (
    <div className="agent-settings">
      <section>
        <h3>{t('agentTelegram.title')}</h3>
        {state && (
          <>
            <p>{t(state.linked ? 'agentTelegram.linked' : 'agentTelegram.linkFirst')}</p>
            {!state.linked &&
              (link ? (
                <a
                  className="mind-secondary-action"
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t('agentTelegram.openBot')}
                </a>
              ) : (
                <button
                  type="button"
                  disabled={busy || !state.bot}
                  className="mind-secondary-action"
                  onClick={() => void connect()}
                >
                  {t('agentTelegram.link')}
                </button>
              ))}
            {state.linked && (
              <div className="agent-key-form">
                <label>
                  {t('models.choose')}
                  <select
                    value={state.model}
                    onChange={(e) => change({ model: e.target.value, serviceTier: 'standard' })}
                  >
                    {models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.titleKey ? t(m.titleKey) : m.title}
                      </option>
                    ))}
                  </select>
                </label>
                {selected?.serviceTiers && selected.serviceTiers.length > 1 && (
                  <label>
                    {t('agentSettings.speed')}
                    <select
                      value={state.serviceTier}
                      onChange={(e) => change({ serviceTier: e.target.value })}
                    >
                      {selected.serviceTiers.map((s) => (
                        <option key={s} value={s}>
                          {t('agentSettings.speeds.' + s)}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <label>
                  {t('rail.minds')}
                  <select
                    value={state.mind_id || ''}
                    onChange={(e) => change({ mind_id: e.target.value || null })}
                  >
                    <option value="">{t('agentTelegram.defaultMind')}</option>
                    {minds.map((m) => (
                      <option key={m.public_id} value={m.public_id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="agent-checkbox">
                  <input
                    type="checkbox"
                    checked={state.webSearch}
                    onChange={(e) => change({ webSearch: e.target.checked })}
                  />
                  {t('composer.tools.web')}
                </label>
                <h3>{t('agentTelegram.secretary')}</h3>
                <p>{t('agentTelegram.secretaryHelp')}</p>
                <p>
                  {t(
                    state.businessConnected
                      ? state.canReply
                        ? 'agentTelegram.allowed'
                        : 'agentTelegram.noReply'
                      : 'agentTelegram.connectHelp',
                    { bot: state.bot ? '@' + state.bot : 'ReMind' }
                  )}
                </p>
                <label>
                  {t('agentTelegram.when')}
                  <select
                    value={state.secretaryMode}
                    onChange={(e) => change({ secretaryMode: e.target.value })}
                  >
                    {['off', 'mentions', 'all'].map((mode) => (
                      <option key={mode} value={mode}>
                        {t('agentTelegram.modes.' + mode)}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="mind-primary-action"
                  disabled={busy}
                  onClick={() => void submit()}
                >
                  {t('minds.editor.saveChanges')}
                </button>
                {saved && <span role="status">{t('agentTelegram.saved')}</span>}
              </div>
            )}
          </>
        )}
        {error && <p role="alert">{t('agentTelegram.failed')}</p>}
      </section>
    </div>
  );
}
