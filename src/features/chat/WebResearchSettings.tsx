import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchApi, writeApiJson, toApiServiceError } from '../../services/api/transport';
import type { components } from '../../generated/openapi';

type WebProfile = components['schemas']['AgentWebResearchSettings'];
type WebUpdate = components['schemas']['AgentWebResearchUpdate'];
const endpoint = '/api/agent/web-research';

export default function WebResearchSettings() {
  const { t } = useTranslation();
  const [saved, setSaved] = useState<WebProfile | null>(null);
  const [draft, setDraft] = useState<WebProfile | null>(null);
  const [key, setKey] = useState('');
  const [clearKey, setClearKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [loadCount, setLoadCount] = useState(0);

  useEffect(() => {
    const request = new AbortController();
    fetchApi<WebProfile>(endpoint, { signal: request.signal })
      .then((data) => {
        if (request.signal.aborted) return;
        setSaved(data);
        setDraft(data);
      })
      .catch(() => {
        if (!request.signal.aborted) setNotice('loadFailed');
      });
    return () => request.abort();
  }, [loadCount]);

  function change(values: Partial<WebProfile>) {
    setNotice('');
    setDraft((state) => (state ? { ...state, ...values } : state));
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || !saved) return;
    const payload: WebUpdate = {
      searchProvider: draft.searchProvider,
      fetchProvider: draft.fetchProvider,
      searchBilling: draft.searchBilling,
      fetchBilling: draft.fetchBilling,
      searchCount: Number.isFinite(draft.searchCount) ? draft.searchCount : saved.searchCount,
      legacyMaxUses: Number.isFinite(draft.legacyMaxUses)
        ? draft.legacyMaxUses
        : saved.legacyMaxUses,
      ...(clearKey ? { clearKey: true } : key.trim() ? { key: key.trim() } : {}),
    };
    setNotice('');
    setBusy(true);
    try {
      const data = await writeApiJson<WebProfile>(endpoint, 'PUT', payload);
      setSaved(data);
      setDraft(data);
      setKey('');
      setClearKey(false);
      setNotice('saved');
    } catch (error) {
      const response = toApiServiceError(error).data as { error?: { code?: string } } | undefined;
      setNotice(response?.error?.code === 'web_key_required' ? 'keyRequired' : 'saveFailed');
    } finally {
      setBusy(false);
    }
  }

  const useSeparateKey =
    draft &&
    ((draft.searchProvider !== 'remind' && draft.searchBilling === 'dedicated') ||
      (draft.fetchProvider !== 'remind' && draft.fetchBilling === 'dedicated'));
  const changed = JSON.stringify(draft) !== JSON.stringify(saved) || !!key || clearKey;

  return (
    <section className="agent-tool-settings" aria-labelledby="web-research-title">
      <header>
        <h3 id="web-research-title">{t('agentWeb.title')}</h3>
        <p>{t('agentWeb.hint')}</p>
      </header>
      {draft ? (
        <form onSubmit={save}>
          <fieldset disabled={busy}>
            <legend>{t('agentWeb.search')}</legend>
            <label>
              <span>{t('agentWeb.provider')}</span>
              <select
                value={draft.searchProvider}
                onChange={(event) =>
                  change({ searchProvider: event.target.value as WebProfile['searchProvider'] })
                }
              >
                <option value="remind">{t('agentWeb.remind')}</option>
                <option value="deepseek-search-api">{t('agentWeb.searchApi')}</option>
                <option value="deepseek-legacy">{t('agentWeb.legacy')}</option>
              </select>
            </label>
            {draft.searchProvider !== 'remind' && (
              <>
                <label>
                  <span>{t('agentWeb.billing')}</span>
                  <select
                    value={draft.searchBilling}
                    onChange={(event) =>
                      change({ searchBilling: event.target.value as WebProfile['searchBilling'] })
                    }
                  >
                    <option value="linked">{t('agentWeb.linked')}</option>
                    <option value="dedicated">{t('agentWeb.dedicated')}</option>
                  </select>
                </label>
                {draft.searchProvider === 'deepseek-search-api' ? (
                  <label>
                    <span>{t('agentWeb.count')}</span>
                    <input
                      type="number"
                      min={1}
                      max={50}
                      required
                      value={Number.isFinite(draft.searchCount) ? draft.searchCount : ''}
                      onChange={(event) => change({ searchCount: event.target.valueAsNumber })}
                    />
                  </label>
                ) : (
                  <label>
                    <span>{t('agentWeb.maxUses')}</span>
                    <input
                      type="number"
                      min={1}
                      max={5}
                      required
                      value={Number.isFinite(draft.legacyMaxUses) ? draft.legacyMaxUses : ''}
                      onChange={(event) => change({ legacyMaxUses: event.target.valueAsNumber })}
                    />
                  </label>
                )}
              </>
            )}
          </fieldset>
          <fieldset disabled={busy}>
            <legend>{t('agentWeb.fetch')}</legend>
            <label>
              <span>{t('agentWeb.provider')}</span>
              <select
                value={draft.fetchProvider}
                onChange={(event) =>
                  change({ fetchProvider: event.target.value as WebProfile['fetchProvider'] })
                }
              >
                <option value="remind">{t('agentWeb.remind')}</option>
                <option value="deepseek-fetch-api">{t('agentWeb.fetchApi')}</option>
              </select>
            </label>
            {draft.fetchProvider === 'deepseek-fetch-api' && (
              <label>
                <span>{t('agentWeb.billing')}</span>
                <select
                  value={draft.fetchBilling}
                  onChange={(event) =>
                    change({ fetchBilling: event.target.value as WebProfile['fetchBilling'] })
                  }
                >
                  <option value="linked">{t('agentWeb.linked')}</option>
                  <option value="dedicated">{t('agentWeb.dedicated')}</option>
                </select>
              </label>
            )}
          </fieldset>
          {(useSeparateKey || draft.hasDedicatedKey) && (
            <fieldset disabled={busy}>
              <legend>{t('agentWeb.credential')}</legend>
              <label className="agent-tool-settings-secret">
                <span>{t('agentSettings.key')}</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  minLength={4}
                  maxLength={4096}
                  value={key}
                  disabled={clearKey}
                  placeholder={draft.hasDedicatedKey ? t('agentSettings.keySaved') : undefined}
                  onChange={(event) => {
                    setKey(event.target.value);
                    setNotice('');
                  }}
                />
              </label>
              {draft.hasDedicatedKey && (
                <label className="agent-tool-settings-check">
                  <input
                    type="checkbox"
                    checked={clearKey}
                    onChange={(event) => {
                      setClearKey(event.target.checked);
                      setKey('');
                      setNotice('');
                    }}
                  />
                  <span>{t('agentWeb.clearKey')}</span>
                </label>
              )}
            </fieldset>
          )}
          {((draft.searchProvider !== 'remind' && draft.searchBilling === 'linked') ||
            (draft.fetchProvider !== 'remind' && draft.fetchBilling === 'linked')) &&
            !draft.hasLinkedKey && <p>{t('agentWeb.linkMissing')}</p>}
          <div className="native-workspace-links">
            <button type="submit" disabled={busy || !changed}>
              {t('projects.save')}
            </button>
          </div>
        </form>
      ) : notice === 'loadFailed' ? (
        <div className="native-workspace-links">
          <button
            type="button"
            onClick={() => {
              setNotice('');
              setLoadCount((count) => count + 1);
            }}
          >
            {t('agentWeb.reload')}
          </button>
        </div>
      ) : (
        <p>{t('agentWeb.loading')}</p>
      )}
      {notice && (
        <p role="status" className="agent-tool-status">
          {t('agentWeb.' + notice)}
        </p>
      )}
    </section>
  );
}
