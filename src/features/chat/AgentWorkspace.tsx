import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { components } from '../../generated/openapi';
import { apiService } from '../../services/api';
import { fetchApi, toApiServiceError, writeApiJson } from '../../services/api/transport';
import { normalizeModelOptions, type ChatModel } from './modelSelection';
import SubagentModelSettings from './SubagentModelSettings';
import WebResearchSettings from './WebResearchSettings';

type RuntimeSettings = components['schemas']['AgentRuntimeSettings'];
const endpoint = '/api/agent/runtime';
const defaults: RuntimeSettings = {
  maxSteps: 16,
  maxToolCallsPerStep: 4,
  maxToolCalls: 32,
  toolTimeSeconds: 180,
  contextCompaction: 'automatic',
  contextSummaryMode: 'excerpts',
  contextSummaryModel: '',
  contextThresholdPercent: 80,
  contextRetainPercent: 16,
  contextRetainTokens: 0,
  contextHeadroomTokens: 4096,
  contextSummaryTokens: 2048,
  contextSummaryRetries: 1,
  modelReplayEnabled: false,
  shellEnabled: false,
  shellTimeoutMs: 10000,
  shellMaxOutputBytes: 12000,
  subagentMaxDepth: 0,
  subagentMaxActive: 2,
  subagentModel: '',
  subagentModelSelection: false,
  subagentAllowedModels: [],
};
const numericFields = [
  ['maxSteps', 1, 32],
  ['maxToolCallsPerStep', 1, 4],
  ['maxToolCalls', 1, 32],
  ['toolTimeSeconds', 30, 180],
] as const;
const contextFields = [
  ['contextThresholdPercent', 'threshold', 20, 99],
  ['contextHeadroomTokens', 'headroom', 0, 65536],
  ['contextRetainTokens', 'retainTokens', 0, 160000],
  ['contextRetainPercent', 'retainPercent', 4, 80],
  ['contextSummaryTokens', 'outputTokens', 512, 8192],
  ['contextSummaryRetries', 'retries', 0, 2],
] as const;

function editableRuntime(data: RuntimeSettings): RuntimeSettings {
  return Object.fromEntries(
    (Object.keys(defaults) as Array<keyof RuntimeSettings>).map((key) => [
      key,
      data[key] ?? defaults[key],
    ])
  ) as RuntimeSettings;
}

export default function AgentWorkspace({
  onOpenPlugins,
  onOpenAutomations,
}: {
  onOpenPlugins: () => void;
  onOpenAutomations: () => void;
}) {
  const { t } = useTranslation();
  const [runtime, setRuntime] = useState<RuntimeSettings | null>(null);
  const [draft, setDraft] = useState<RuntimeSettings | null>(null);
  const [models, setModels] = useState<ChatModel[]>([]);
  const [catalogStatus, setCatalogStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [catalogRequest, setCatalogRequest] = useState(0);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loadCount, setLoadCount] = useState(0);
  const changed = JSON.stringify(draft) !== JSON.stringify(runtime);

  useEffect(() => {
    const controller = new AbortController();
    fetchApi<RuntimeSettings>(endpoint, { signal: controller.signal })
      .then((data) => {
        if (controller.signal.aborted) return;
        const saved = editableRuntime(data);
        setRuntime(saved);
        setDraft(saved);
      })
      .catch(() => {
        if (!controller.signal.aborted) setNotice('loadFailed');
      });
    return () => controller.abort();
  }, [loadCount]);

  useEffect(() => {
    const controller = new AbortController();
    void apiService
      .listModels()
      .then((results) => {
        if (!controller.signal.aborted) {
          setModels(
            normalizeModelOptions(results).filter(
              ({ id }) =>
                id === 'base' ||
                id === 'harness' ||
                id === 'claude_sonnet_5_5' ||
                /^(?:key|codex|chatgpt)\//.test(id)
            )
          );
          setCatalogStatus('ready');
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setCatalogStatus('error');
      });
    return () => controller.abort();
  }, [catalogRequest]);

  function change(values: Partial<RuntimeSettings>) {
    setNotice('');
    setDraft((state) => (state ? { ...state, ...values } : state));
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft || !runtime) return;
    setNotice('');
    setBusy(true);
    try {
      const data = await writeApiJson<RuntimeSettings>(endpoint, 'PUT', {
        ...draft,
        ...Object.fromEntries(
          contextFields
            .filter(
              ([field]) =>
                !Number.isFinite(draft[field]) &&
                (draft.contextSummaryMode === 'excerpts' ||
                  (field === 'contextRetainPercent' && draft.contextRetainTokens > 0))
            )
            .map(([field]) => [field, runtime[field]])
        ),
        shellTimeoutMs:
          !draft.shellEnabled && !Number.isFinite(draft.shellTimeoutMs)
            ? runtime.shellTimeoutMs
            : draft.shellTimeoutMs,
        shellMaxOutputBytes:
          !draft.shellEnabled && !Number.isFinite(draft.shellMaxOutputBytes)
            ? runtime.shellMaxOutputBytes
            : draft.shellMaxOutputBytes,
        ...(draft.subagentMaxDepth === 0 && !Number.isFinite(draft.subagentMaxActive)
          ? { subagentMaxActive: runtime.subagentMaxActive }
          : {}),
      });
      const saved = editableRuntime(data);
      setRuntime(saved);
      setDraft(saved);
      window.dispatchEvent(new Event('remind:model-catalog'));
      setNotice('saved');
    } catch (error) {
      const data = toApiServiceError(error).data as { error?: { code?: string } } | undefined;
      switch (data?.error?.code) {
        case 'subagent_model_unavailable':
          setNotice('subagentRoutes.unavailable');
          break;
        case 'subagent_allowed_models_required':
          setNotice('subagentRoutes.required');
          break;
        default:
          setNotice('saveFailed');
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="native-workspace workspace-profile">
      {draft ? (
        <form className="agent-runtime-form" onSubmit={save}>
          <fieldset disabled={busy}>
            <legend>{t('workspace.agentLimits')}</legend>
            {numericFields.map(([field, min, max]) => (
              <label key={field}>
                <span>{t('workspace.' + field)}</span>
                <input
                  type="number"
                  required
                  min={min}
                  max={max}
                  value={Number.isFinite(draft[field]) ? draft[field] : ''}
                  onChange={(event) => change({ [field]: event.target.valueAsNumber })}
                />
              </label>
            ))}
          </fieldset>
          <fieldset disabled={busy}>
            <legend>{t('workspace.context')}</legend>
            <label>
              <span>{t('workspace.contextCompaction')}</span>
              <select
                value={draft.contextCompaction}
                onChange={(event) => {
                  change({
                    contextCompaction: event.target.value === 'manual' ? 'manual' : 'automatic',
                  });
                }}
              >
                <option value="automatic">{t('workspace.compactionAutomatic')}</option>
                <option value="manual">{t('workspace.compactionManual')}</option>
              </select>
            </label>
            <label>
              <span>{t('workspace.contextSummary.method')}</span>
              <select
                value={draft.contextSummaryMode}
                onChange={(event) =>
                  change({
                    contextSummaryMode: event.target.value === 'model' ? 'model' : 'excerpts',
                  })
                }
              >
                <option value="excerpts">{t('workspace.contextSummary.excerpts')}</option>
                <option value="model">{t('workspace.contextSummary.model')}</option>
              </select>
            </label>
            {draft.contextSummaryMode === 'model' && (
              <>
                <p>{t('workspace.contextSummary.modelHint')}</p>
                <label>
                  <span>{t('workspace.contextSummary.route')}</span>
                  <select
                    value={draft.contextSummaryModel}
                    onChange={(event) => change({ contextSummaryModel: event.target.value })}
                  >
                    <option value="">{t('workspace.contextSummary.chatModel')}</option>
                    {draft.contextSummaryModel &&
                      !models.some(({ id }) => id === draft.contextSummaryModel) && (
                        <option value={draft.contextSummaryModel} disabled>
                          {t('agentSettings.modelUnavailable')}
                        </option>
                      )}
                    {models.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.titleKey
                          ? t(model.titleKey, { defaultValue: model.title })
                          : model.title}
                      </option>
                    ))}
                  </select>
                </label>
                <details className="agent-compaction-controls">
                  <summary>{t('workspace.contextSummary.limits')}</summary>
                  {contextFields.map(([field, label, min, max]) => (
                    <label key={field}>
                      <span>{t('workspace.contextSummary.' + label)}</span>
                      <input
                        type="number"
                        required
                        min={min}
                        max={
                          field === 'contextRetainPercent'
                            ? Math.min(max, draft.contextThresholdPercent - 1)
                            : max
                        }
                        disabled={field === 'contextRetainPercent' && draft.contextRetainTokens > 0}
                        value={Number.isFinite(draft[field]) ? draft[field] : ''}
                        onChange={(event) => change({ [field]: event.target.valueAsNumber })}
                      />
                    </label>
                  ))}
                  <p>{t('workspace.contextSummary.retainHint')}</p>
                </details>
              </>
            )}
          </fieldset>
          <fieldset disabled={busy}>
            <legend>{t('workspace.modelReplay.title')}</legend>
            <p>{t('workspace.modelReplay.hint')}</p>
            <label className="agent-tool-settings-check">
              <input
                type="checkbox"
                checked={draft.modelReplayEnabled}
                onChange={(event) => change({ modelReplayEnabled: event.target.checked })}
              />
              <span>{t('workspace.modelReplay.enable')}</span>
            </label>
          </fieldset>
          <fieldset disabled={busy}>
            <legend>{t('agentExecution.shell')}</legend>
            <p>{t('agentExecution.shellHint')}</p>
            {draft.shellEnabled && <p>{t('agentExecution.shellPipelineHint')}</p>}
            <p>{t('skillLibrary.scriptSettings')}</p>
            <label className="agent-tool-settings-check">
              <input
                type="checkbox"
                checked={draft.shellEnabled}
                onChange={(event) => change({ shellEnabled: event.target.checked })}
              />
              <span>{t('agentExecution.shellEnable')}</span>
            </label>
            {draft.shellEnabled && (
              <>
                <label>
                  <span>{t('agentExecution.shellTimeout')}</span>
                  <input
                    type="number"
                    min={100}
                    max={15000}
                    required
                    value={Number.isFinite(draft.shellTimeoutMs) ? draft.shellTimeoutMs : ''}
                    onChange={(event) => change({ shellTimeoutMs: event.target.valueAsNumber })}
                  />
                </label>
                <label>
                  <span>{t('agentExecution.shellOutput')}</span>
                  <input
                    type="number"
                    min={256}
                    max={16000}
                    required
                    value={
                      Number.isFinite(draft.shellMaxOutputBytes) ? draft.shellMaxOutputBytes : ''
                    }
                    onChange={(event) =>
                      change({ shellMaxOutputBytes: event.target.valueAsNumber })
                    }
                  />
                </label>
              </>
            )}
          </fieldset>
          <fieldset disabled={busy}>
            <legend>{t('agentExecution.subagents')}</legend>
            <p>{t('agentExecution.subagentsHint')}</p>
            <label>
              <span>{t('agentExecution.depth')}</span>
              <input
                type="number"
                min={0}
                max={2}
                required
                value={Number.isFinite(draft.subagentMaxDepth) ? draft.subagentMaxDepth : ''}
                onChange={(event) => change({ subagentMaxDepth: event.target.valueAsNumber })}
              />
            </label>
            {draft.subagentMaxDepth > 0 && (
              <>
                <label>
                  <span>{t('agentExecution.active')}</span>
                  <input
                    type="number"
                    min={1}
                    max={3}
                    required
                    value={Number.isFinite(draft.subagentMaxActive) ? draft.subagentMaxActive : ''}
                    onChange={(event) => change({ subagentMaxActive: event.target.valueAsNumber })}
                  />
                </label>
                <label>
                  <span>{t('agentExecution.model')}</span>
                  <select
                    value={draft.subagentModel}
                    onChange={(event) => change({ subagentModel: event.target.value })}
                  >
                    <option value="">{t('agentExecution.chatModel')}</option>
                    {draft.subagentModel &&
                      !models.some(({ id }) => id === draft.subagentModel) && (
                        <option value={draft.subagentModel} disabled>
                          {t('agentSettings.modelUnavailable')}
                        </option>
                      )}
                    {models.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.titleKey
                          ? t(model.titleKey, { defaultValue: model.title })
                          : model.title}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            <SubagentModelSettings
              enabled={draft.subagentModelSelection}
              selected={draft.subagentAllowedModels}
              models={models}
              status={catalogStatus}
              retry={() => {
                setCatalogStatus('loading');
                setCatalogRequest((count) => count + 1);
              }}
              onEnable={(enabled) => change({ subagentModelSelection: enabled })}
              onSelect={(selected) => change({ subagentAllowedModels: selected })}
            />
          </fieldset>
          <div className="native-workspace-links">
            <button
              type="submit"
              disabled={busy || !changed || (draft.subagentModelSelection && !draft.subagentAllowedModels.length)}
            >
              {t('projects.save')}
            </button>
            <button type="button" disabled={busy} onClick={() => change(defaults)}>
              {t('workspace.restoreDefaults')}
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
        <p>{t('agentExecution.loading')}</p>
      )}
      {notice && (
        <p role="status" className="agent-tool-status">
          {t('agentExecution.' + notice)}
        </p>
      )}
      <WebResearchSettings />
      <div className="native-workspace-links">
        <button type="button" onClick={onOpenPlugins}>
          {t('plugins.title')}
        </button>
        <button type="button" onClick={onOpenAutomations}>
          {t('automations.title')}
        </button>
      </div>
    </section>
  );
}
