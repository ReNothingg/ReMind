import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowUp, Check, KeyRound, Plus, Trash2 } from 'lucide-react';
import type { components } from '../../generated/openapi';
import { apiService } from '../../services/api';
import { fetchApi, toApiServiceError, writeApiJson } from '../../services/api/transport';
import { indexModelCatalog } from './modelCatalogSearch';
import { isImageToolModel, normalizeModelOptions, type ChatModel } from './modelSelection';
import ChatGPTConnection from './ChatGPTConnection';
import CodexSettings from './CodexSettings';
import ProviderModelSettings from './ProviderModelSettings';
import ProviderRetrySettings from './ProviderRetrySettings';
import {
  defaultRetryPolicy,
  modelReasoningLevels,
  type ProviderModel as Candidate,
} from './providerModelContract';

type Provider = components['schemas']['AgentProviderConnection'];
type Catalog = components['schemas']['AgentProviderConnections'];
const protocols = [
  'openai-completions',
  'openai-responses',
  'anthropic-messages',
  'google-generative-ai',
] as const satisfies readonly Provider['protocol'][];

export default function ProviderSettings({
  defaultModel,
  onDefaultModelChange,
}: {
  defaultModel: string;
  onDefaultModelChange: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [availableModels, setAvailableModels] = useState<ChatModel[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [draft, setDraft] = useState<Provider | null>(null);
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [found, setFound] = useState<Candidate[]>([]);
  const [query, setQuery] = useState('');
  const [modelId, setModelId] = useState('');
  const [modelTitle, setModelTitle] = useState('');
  const [confirmRemove, setConfirmRemove] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetchApi<Catalog>('/api/agent/providers', { signal: controller.signal })
      .then((result) => setProviders(result.providers))
      .catch(() => {
        if (!controller.signal.aborted) setError('provider_catalog_failed');
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    let active = true;
    const refresh = () => {
      void apiService
        .listModelCatalog()
        .then(({ models }) => {
          if (active)
            setAvailableModels(
              normalizeModelOptions(models).filter((model) => !isImageToolModel(model))
            );
        })
        .catch(() => undefined);
    };
    refresh();
    window.addEventListener('remind:model-catalog', refresh);
    return () => {
      active = false;
      window.removeEventListener('remind:model-catalog', refresh);
    };
  }, []);
  function open(provider: Provider) {
    setFound([]);
    setQuery('');
    setKey('');
    setModelId('');
    setModelTitle('');
    setError('');
    setConfirmRemove(false);
    setDraft(provider);
  }
  async function perform(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (reason) {
      const response = toApiServiceError(reason).data as { error?: { code?: string } } | undefined;
      setError(response?.error?.code || 'provider_catalog_failed');
    } finally {
      setBusy(false);
    }
  }
  const update = (values: Partial<Provider>) =>
    setDraft((current) => (current ? { ...current, ...values } : null));
  const updateConnection = (values: Partial<Provider>) => {
    setFound([]);
    setQuery('');
    update(values);
  };
  const endpoint = draft ? '/api/agent/providers/' + encodeURIComponent(draft.id) : '';
  const stored = providers.find((provider) => provider.id === draft?.id);
  const base = draft?.baseUrl.trim().replace(/\/+$/, '') || draft?.defaultBaseUrl || '';
  const routeChanged = Boolean(
    stored?.connected && (stored.baseUrl !== base || draft?.protocol !== stored.protocol)
  );
  const needsKey = draft ? !draft.connected || routeChanged : false;
  const offersModels = !needsKey || Boolean(key.trim());
  const customCatalog = draft?.catalogMode === 'custom';
  const data = draft
    ? {
        key,
        baseUrl: draft.baseUrl.trim(),
        expectedRevision: draft.revision,
        retryPolicy: draft.retryPolicy || defaultRetryPolicy,
        ...(draft.custom ? { name: draft.name, protocol: draft.protocol } : {}),
      }
    : {};
  function save(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    void perform(async () => {
      const result = await writeApiJson<Catalog>(endpoint, 'PUT', {
        ...data,
        catalogMode: draft.catalogMode,
        ...(customCatalog ? { models: draft.models } : {}),
      });
      setProviders(result.providers);
      setDraft(null);
      setKey('');
      window.dispatchEvent(new Event('remind:model-catalog'));
    });
  }
  function refreshModels() {
    if (!draft) return;
    void perform(async () => {
      const result = await writeApiJson<Catalog>(endpoint, 'POST', {
        expectedRevision: draft.revision,
      });
      const latest = result.providers.find((provider) => provider.id === draft.id);
      setProviders(result.providers);
      if (latest)
        update({ models: latest.models, modelCount: latest.modelCount, revision: latest.revision });
      setFound([]);
      setQuery('');
      window.dispatchEvent(new Event('remind:model-catalog'));
    });
  }
  function reloadProvider() {
    void perform(async () => {
      const result = await fetchApi<Catalog>('/api/agent/providers');
      setProviders(result.providers);
      const latest = result.providers.find((provider) => provider.id === draft?.id);
      if (latest) open(latest);
      else {
        setDraft(null);
        setKey('');
      }
      window.dispatchEvent(new Event('remind:model-catalog'));
    });
  }
  function switchModel(model: Candidate) {
    if (!draft) return;
    update({
      models: draft.models.some(({ slug }) => slug === model.slug)
        ? draft.models.filter(({ slug }) => slug !== model.slug)
        : [...draft.models, model],
    });
  }
  function move(index: number, offset: number) {
    if (!draft || index + offset < 0 || index + offset >= draft.models.length) return;
    const models = [...draft.models];
    const selected = models.splice(index, 1)[0];
    if (!selected) return;
    models.splice(index + offset, 0, selected);
    update({ models });
  }
  const searchFound = useMemo(
    () => indexModelCatalog(found, ({ slug, title }) => ({ names: [title, slug] })),
    [found]
  );
  const available = searchFound(query);
  const inherited = found.length
    ? found
    : stored?.catalogMode === 'provider' && !routeChanged && !key
      ? stored.models
      : [];
  return (
    <div className="agent-settings">
      <section className="agent-default-model">
        <label>
          <span>{t('agentSettings.defaultModel')}</span>
          <select
            value={defaultModel}
            disabled={!availableModels.length}
            onChange={(event) => {
              onDefaultModelChange(event.target.value);
            }}
          >
            <option value="">{t('workspace.compactionAutomatic')}</option>
            {defaultModel && !availableModels.some((model) => model.id === defaultModel) && (
              <option value={defaultModel} disabled>
                {t('agentSettings.modelUnavailable')}
              </option>
            )}
            {availableModels.map((model) => (
              <option value={model.id} key={model.id}>
                {model.titleKey ? t(model.titleKey, { defaultValue: model.title }) : model.title}
              </option>
            ))}
          </select>
        </label>
      </section>
      <section className="agent-provider-section">
        <div className="agent-settings-title">
          <KeyRound size={19} />
          <h3>{t('agentSettings.keys')}</h3>
        </div>
        <div className="agent-provider-list">
          {providers
            .filter((provider) => provider.id !== 'custom' || provider.connected)
            .map((provider) => (
              <button
                type="button"
                key={provider.id}
                disabled={busy}
                aria-pressed={draft?.id === provider.id}
                onClick={() => open(provider)}
              >
                <span>{provider.name}</span>
                <small>
                  {provider.connected
                    ? t('agentSettings.modelCount', { count: provider.modelCount })
                    : t('agentSettings.notConnected')}
                </small>
              </button>
            ))}
        </div>
        <button
          type="button"
          className="agent-provider-add"
          disabled={busy}
          onClick={() =>
            open({
              id: 'custom-' + crypto.randomUUID().slice(0, 8),
              name: '',
              protocol: protocols[0],
              connected: false,
              custom: true,
              baseUrl: '',
              defaultBaseUrl: '',
              catalogMode: 'custom',
              revision: null,
              modelCount: 0,
              models: [],
            })
          }
        >
          <Plus size={16} />
          {t('agentSettings.addProvider')}
        </button>
        {draft && (
          <form className="agent-key-form agent-provider-editor" onSubmit={save}>
            {draft.custom && (
              <>
                <label>
                  {t('agentSettings.displayName')}
                  <input
                    required
                    value={draft.name}
                    maxLength={80}
                    disabled={busy}
                    onChange={(event) => update({ name: event.target.value })}
                  />
                </label>
                <label>
                  {t('agentSettings.protocol')}
                  <select
                    value={draft.protocol}
                    disabled={busy}
                    onChange={(event) => {
                      const protocol = protocols.find((item) => item === event.target.value);
                      if (protocol) updateConnection({ protocol });
                    }}
                  >
                    {protocols.map((protocol) => (
                      <option key={protocol} value={protocol}>
                        {t('agentSettings.protocols.' + protocol)}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            <label>
              {t('agentSettings.endpoint')}
              <input
                type="url"
                required={draft.custom}
                disabled={busy}
                value={draft.baseUrl}
                placeholder={draft.defaultBaseUrl || undefined}
                onChange={(event) => updateConnection({ baseUrl: event.target.value })}
                autoCapitalize="none"
                spellCheck={false}
                maxLength={1024}
                dir="ltr"
              />
            </label>
            <label>
              {t('agentSettings.key')}
              <input
                type="password"
                value={key}
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                maxLength={4096}
                disabled={busy}
                required={needsKey}
                placeholder={needsKey ? undefined : t('agentSettings.keySaved')}
                onChange={(event) => {
                  setKey(event.target.value);
                  setFound([]);
                  setQuery('');
                }}
              />
            </label>
            {routeChanged && (
              <p className="agent-provider-hint">
                {t('agentSettings.errors.provider_key_for_endpoint_required')}
              </p>
            )}
            <ProviderRetrySettings
              value={draft.retryPolicy || defaultRetryPolicy}
              onChange={(retryPolicy) => update({ retryPolicy })}
              disabled={busy}
            />
            <label>
              {t('agentSettings.catalogMode')}
              <select
                value={draft.catalogMode}
                disabled={busy}
                onChange={(event) =>
                  update({ catalogMode: event.target.value === 'provider' ? 'provider' : 'custom' })
                }
              >
                <option value="provider">{t('agentSettings.providerCatalog')}</option>
                <option value="custom">{t('agentSettings.customCatalog')}</option>
              </select>
            </label>
            <div className="agent-provider-actions">
              <button
                type="button"
                disabled={busy || !offersModels}
                onClick={() =>
                  void perform(async () => {
                    const result = await writeApiJson<{ models: Candidate[] }>(
                      endpoint + '/discover',
                      'POST',
                      data
                    );
                    setFound(result.models);
                    setQuery('');
                  })
                }
              >
                {t('agentSettings.discover')}
              </button>
              {!customCatalog && stored?.catalogMode === 'provider' && !routeChanged && !key && (
                <button type="button" disabled={busy} onClick={refreshModels}>
                  {t('agentSettings.refresh', { name: stored.name })}
                </button>
              )}
            </div>
            {!customCatalog &&
              (inherited.length === 0 ? (
                <p className="agent-provider-hint">{t('agentSettings.catalogOnSave')}</p>
              ) : (
                <ul
                  className="agent-provider-catalog agent-provider-inherited"
                  aria-label={t('agentSettings.providerCatalog')}
                >
                  {inherited.map(({ slug, title }) => (
                    <li key={slug}>{title}</li>
                  ))}
                </ul>
              ))}
            {customCatalog && found.length > 0 && (
              <div className="agent-provider-catalog">
                <input
                  aria-label={t('agentSettings.search')}
                  placeholder={t('agentSettings.search')}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
                {available.map((model) => (
                  <label key={model.slug} className="agent-provider-candidate">
                    <input
                      type="checkbox"
                      checked={draft.models.some(({ slug }) => slug === model.slug)}
                      disabled={busy}
                      onChange={() => switchModel(model)}
                    />
                    <span>{model.title}</span>
                  </label>
                ))}
              </div>
            )}
            {customCatalog && (
              <div className="agent-provider-add-model">
                <input
                  value={modelId}
                  aria-label={t('agentSettings.modelId')}
                  placeholder={t('agentSettings.modelId')}
                  disabled={busy}
                  onChange={(event) => setModelId(event.target.value)}
                />
                <input
                  value={modelTitle}
                  aria-label={t('agentSettings.modelDisplayName')}
                  placeholder={t('agentSettings.modelDisplayName')}
                  disabled={busy}
                  onChange={(event) => setModelTitle(event.target.value)}
                />
                <button
                  type="button"
                  disabled={
                    busy ||
                    !modelId.trim() ||
                    draft.models.some(({ slug }) => slug === modelId.trim())
                  }
                  onClick={() => {
                    update({
                      models: [
                        ...draft.models,
                        { slug: modelId.trim(), title: modelTitle.trim() || modelId.trim() },
                      ],
                    });
                    setModelId('');
                    setModelTitle('');
                  }}
                >
                  {t('agentSettings.addModel')}
                </button>
              </div>
            )}
            {customCatalog && draft.models.length === 0 && (
              <p className="agent-provider-hint">{t('agentSettings.customCatalogEmpty')}</p>
            )}
            {customCatalog && draft.models.length > 0 && (
              <ol className="agent-provider-order">
                {draft.models.map((model, index) => (
                  <li key={model.slug} className="agent-provider-model-row">
                    <ProviderModelSettings
                      model={model}
                      levels={modelReasoningLevels(draft.id, draft.protocol)}
                      editableWire={draft.id !== 'deepseek' && draft.protocol.startsWith('openai-')}
                      disabled={busy}
                      onChange={(next) =>
                        update({
                          models: draft.models.map((item) =>
                            item.slug === model.slug ? next : item
                          ),
                        })
                      }
                    />
                    <button
                      type="button"
                      aria-label={t('agentSettings.moveUp', { name: model.title })}
                      disabled={busy || index === 0}
                      onClick={() => move(index, -1)}
                    >
                      <ArrowUp size={16} />
                    </button>
                    <button
                      type="button"
                      aria-label={t('agentSettings.moveDown', { name: model.title })}
                      disabled={busy || index === draft.models.length - 1}
                      onClick={() => move(index, 1)}
                    >
                      <ArrowDown size={16} />
                    </button>
                    <button
                      type="button"
                      aria-label={t('agentSettings.removeModel', { name: model.title })}
                      disabled={busy}
                      onClick={() => switchModel(model)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </li>
                ))}
              </ol>
            )}
            <div className="agent-provider-actions">
              <button
                type="submit"
                disabled={busy || !offersModels || (customCatalog && !draft.models.length)}
              >
                <Check size={16} />
                {t('projects.save')}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setDraft(null);
                  setKey('');
                }}
              >
                {t('projects.cancel')}
              </button>
              {draft.connected && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    if (!confirmRemove) {
                      setConfirmRemove(true);
                      return;
                    }
                    void perform(async () => {
                      const result = await writeApiJson<Catalog>(endpoint, 'DELETE', {
                        expectedRevision: draft.revision,
                      });
                      setProviders(result.providers);
                      setDraft(null);
                      setKey('');
                      window.dispatchEvent(new Event('remind:model-catalog'));
                    });
                  }}
                >
                  {t(
                    confirmRemove
                      ? 'agentSettings.confirmDisconnect'
                      : 'agentSettings.removeProvider'
                  )}
                </button>
              )}
            </div>
          </form>
        )}
        {error && (
          <div role="alert" className="account-connected-app-error agent-provider-error">
            {error === 'provider_retry_invalid'
              ? t('agentRetry.invalid')
              : error === 'provider_model_config_invalid'
                ? t('agentModel.invalid')
                : t('agentSettings.errors.' + error, {
                    defaultValue: t('agentSettings.errors.provider_catalog_failed'),
                  })}
            {error === 'provider_connection_changed' && (
              <button type="button" disabled={busy} onClick={reloadProvider}>
                {t('agentSettings.reloadProvider')}
              </button>
            )}
          </div>
        )}
      </section>
      <CodexSettings />
      <section aria-label={t('agentSettings.subscription')} className="agent-subscription">
        <ChatGPTConnection />
      </section>
    </div>
  );
}
