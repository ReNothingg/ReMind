import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../context/AuthContext';
import {
  fetchApi,
  toApiServiceError,
  writeApiJson as requestChange,
} from '../../services/api/transport';
import { isImageToolModel, type ChatModel } from '../chat/modelSelection';
import { useProjects } from '../projects/useProjects';
import './automation.css';

type Timing =
  | { kind: 'after' | 'every'; seconds: number }
  | { kind: 'at'; at: string }
  | { kind: 'daily'; zone: string; time: string }
  | { kind: 'weekly'; zone: string; time: string; weekdays: number[] }
  | { kind: 'monthly'; zone: string; time: string; day: number }
  | { kind: 'cron'; zone: string; expression: string };

type Run = {
  id: string;
  session_id: string | null;
  queued_at: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  error: string | null;
};

type Task = {
  id: string;
  title: string;
  prompt: string;
  model: string;
  enabled: boolean;
  web_search: boolean;
  timing: Timing;
  workspace_id: string | null;
  target_session_id: string | null;
  next_run_at: string | null;
  last_run: Run | null;
};

type Proposal = {
  id: string;
  operation: 'create' | 'edit' | 'pause' | 'resume' | 'run' | 'delete';
  task: Task | null;
  changes: Partial<Task>;
  stale: boolean;
  applied_at: string | null;
};

type Props = {
  models: ChatModel[];
  selectedModel: string;
  sessions: { session_id: string; title?: string | null; source?: string | null }[];
  onOpenAuth: () => void;
  onOpenChat: (id: string) => void;
};

const timings = ['at', 'after', 'every', 'daily', 'weekly', 'monthly', 'cron'] as const;
const weekdays = [1, 2, 3, 4, 5, 6, 7];
const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
const initialTiming = (kind: Timing['kind']): Timing => {
  switch (kind) {
    case 'at':
      return { kind, at: '' };
    case 'after':
    case 'every':
      return { kind, seconds: 3600 };
    case 'daily':
      return { kind, zone: browserZone(), time: '09:00' };
    case 'weekly':
      return { kind, zone: browserZone(), time: '09:00', weekdays: [1] };
    case 'monthly':
      return { kind, zone: browserZone(), time: '09:00', day: 1 };
    case 'cron':
      return { kind, zone: browserZone(), expression: '0 9 * * 1-5' };
  }
};

function userLocalInput(instant: string) {
  if (!instant) return '';
  const date = new Date(instant);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function TimingEditor({ timing, update }: { timing: Timing; update: (timing: Timing) => void }) {
  const { t, i18n } = useTranslation();
  return (
    <>
      <label>
        {t('automations.frequency')}
        <select
          value={timing.kind}
          onChange={(e) => update(initialTiming(e.target.value as Timing['kind']))}
        >
          {timings.map((kind) => (
            <option key={kind} value={kind}>
              {t(`automations.kinds.${kind}`)}
            </option>
          ))}
        </select>
      </label>
      {timing.kind === 'at' && (
        <label>
          {t('automations.dateTime')}
          <input
            required
            type="datetime-local"
            value={userLocalInput(timing.at)}
            onChange={(event) => {
              const value = event.target.value;
              update({ ...timing, at: value ? new Date(value).toISOString() : '' });
            }}
          />
        </label>
      )}
      {'seconds' in timing && (
        <label>
          {t('automations.minutes')}
          <input
            required
            type="number"
            min={1}
            max={527040}
            value={timing.seconds / 60 || ''}
            onChange={(e) => update({ ...timing, seconds: Number(e.target.value) * 60 })}
          />
        </label>
      )}
      {'zone' in timing && (
        <label>
          {t('automations.timeZone')}
          <input
            required
            maxLength={80}
            value={timing.zone}
            onChange={(e) => update({ ...timing, zone: e.target.value })}
          />
        </label>
      )}
      {'time' in timing && (
        <label>
          {t('automations.localTime')}
          <input
            type="time"
            required
            value={timing.time}
            onChange={(e) => update({ ...timing, time: e.target.value })}
          />
        </label>
      )}
      {timing.kind === 'weekly' && (
        <fieldset className="automation-weekdays">
          <legend>{t('automations.weekdays')}</legend>
          {weekdays.map((day) => (
            <label key={day}>
              <input
                type="checkbox"
                checked={timing.weekdays.includes(day)}
                onChange={(e) =>
                  update({
                    ...timing,
                    weekdays: e.target.checked
                      ? [...timing.weekdays, day]
                      : timing.weekdays.filter((value) => value !== day),
                  })
                }
              />
              {new Intl.DateTimeFormat(i18n.language, { weekday: 'short', timeZone: 'UTC' }).format(
                new Date(Date.UTC(2025, 0, day + 5))
              )}
            </label>
          ))}
        </fieldset>
      )}
      {timing.kind === 'monthly' && (
        <label>
          {t('automations.monthDay')}
          <input
            type="number"
            required
            min={1}
            max={31}
            value={timing.day || ''}
            onChange={(e) => update({ ...timing, day: Number(e.target.value) })}
          />
        </label>
      )}
      {timing.kind === 'cron' && (
        <label>
          {t('automations.cron')}
          <input
            required
            maxLength={160}
            dir="ltr"
            value={timing.expression}
            onChange={(e) => update({ ...timing, expression: e.target.value })}
          />
        </label>
      )}
    </>
  );
}

function describeTiming(timing: Timing, locale: string, minutes: string): string {
  if ('seconds' in timing) {
    return `${new Intl.NumberFormat(locale).format(timing.seconds / 60)} ${minutes.toLowerCase()}`;
  }
  if (timing.kind === 'at') {
    return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'long' }).format(
      new Date(timing.at)
    );
  }
  if (timing.kind === 'cron') return `${timing.expression} · ${timing.zone}`;
  const clock = `${timing.time} · ${timing.zone}`;
  if (timing.kind === 'weekly') {
    const days = new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' });
    return `${timing.weekdays.map((day) => days.format(new Date(Date.UTC(2025, 0, day + 5)))).join(', ')} · ${clock}`;
  }
  return timing.kind === 'monthly' ? `${timing.day} · ${clock}` : clock;
}

function AutomationReview({
  id,
  models,
  projects,
  sessions,
  onApplied,
}: {
  id: string;
  models: ChatModel[];
  projects: { id: string; name: string }[];
  sessions: Props['sessions'];
  onApplied: () => Promise<unknown>;
}) {
  const { t, i18n } = useTranslation();
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [error, setError] = useState('');
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState(false);
  const path = `/api/automations/proposals/${id}`;
  function errorCode(reason: unknown) {
    const data = toApiServiceError(reason).data as { error?: { code?: string } } | undefined;
    return data?.error?.code || 'automation_unavailable';
  }
  useEffect(() => {
    const controller = new AbortController();
    fetchApi<{ proposal: Proposal }>(path, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setProposal(result.proposal);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(errorCode(reason));
      });
    return () => controller.abort();
  }, [path]);

  async function accept() {
    if (!proposal || applying || applied || proposal.stale) return;
    setApplying(true);
    setError('');
    try {
      await requestChange(`${path}/apply`, 'POST', {});
      setApplied(true);
      await onApplied();
    } catch (reason) {
      setError(errorCode(reason));
    } finally {
      setApplying(false);
    }
  }

  const configured = { ...proposal?.task, ...proposal?.changes };
  const model = models.find((item) => item.id === configured.model);
  const destination = configured.target_session_id
    ? sessions.find((session) => session.session_id === configured.target_session_id)?.title ||
      t('automations.currentTarget')
    : configured.workspace_id
      ? projects.find((project) => project.id === configured.workspace_id)?.name ||
        t('automations.currentTarget')
      : t('automations.newChat');

  return (
    <section
      className="automation-task automation-review"
      aria-label={t('automations.proposal.title')}
    >
      <h2>{t('automations.proposal.title')}</h2>
      {error && (
        <p role="alert">
          {t(`automations.errors.${error}`, {
            defaultValue: t('automations.errors.automation_unavailable'),
          })}
        </p>
      )}
      {!error && !proposal && <p role="status">{t('common.loading')}</p>}
      {(applied || proposal?.applied_at) && (
        <p role="status">{t('automations.proposal.applied')}</p>
      )}
      {proposal?.stale && <p role="alert">{t('automations.errors.automation_proposal_changed')}</p>}
      {proposal && !proposal.applied_at && !applied && !proposal.stale && (
        <>
          <p>{t(`automations.proposal.operations.${proposal.operation}`)}</p>
          <dl>
            <dt>{t('automations.name')}</dt>
            <dd>{configured.title}</dd>
            {configured.prompt && (
              <>
                <dt>{t('automations.prompt')}</dt>
                <dd className="automation-review-prompt">{configured.prompt}</dd>
              </>
            )}
            {configured.model && (
              <>
                <dt>{t('automations.model')}</dt>
                <dd>{model?.titleKey ? t(model.titleKey) : model?.title || configured.model}</dd>
              </>
            )}
            <dt>{t('automations.destination')}</dt>
            <dd>{destination}</dd>
            {configured.timing && (
              <>
                <dt>{t(`automations.kinds.${configured.timing.kind}`)}</dt>
                <dd>
                  {describeTiming(configured.timing, i18n.language, t('automations.minutes'))}
                </dd>
              </>
            )}
          </dl>
          {configured.web_search && <p>{t('automations.proposal.webEnabled')}</p>}
          <div className="automation-actions">
            <button type="button" disabled={applying} onClick={() => void accept()}>
              {t('automations.proposal.confirm')}
            </button>
          </div>
        </>
      )}
    </section>
  );
}

function AutomationList({ models, selectedModel, sessions, onOpenChat }: Props) {
  const { t, i18n } = useTranslation();
  const { user } = useAuth();
  const { projects } = useProjects(user?.id);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [draft, setDraft] = useState<Task | null>(null);
  const [remove, setRemove] = useState<string | null>(null);
  const [receiptTask, setReceiptTask] = useState<string | null>(null);
  const [receipts, setReceipts] = useState<Run[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const textModels = models.filter((model) => !isImageToolModel(model));
  const webSessions = sessions.filter((session) => !session.source || session.source === 'web');
  const proposalId = new URLSearchParams(window.location.search).get('proposal');

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const result = await fetchApi<{ tasks: Task[] }>('/api/automations', {
      signal: signal ?? null,
    });
    if (!signal?.aborted) setTasks(result.tasks);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const load = () =>
      Promise.all([
        refresh(controller.signal),
        receiptTask
          ? fetchApi<{ runs: Run[] }>(`/api/automations/${receiptTask}/runs`, {
              signal: controller.signal,
            }).then(({ runs }) => {
              if (!controller.signal.aborted) setReceipts(runs);
            })
          : Promise.resolve(),
      ])
        .catch(() => {
          if (!controller.signal.aborted) setError('automation_unavailable');
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    void load();
    const interval = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 7000);
    return () => {
      window.clearInterval(interval);
      controller.abort();
    };
  }, [refresh, receiptTask]);

  function execute(operation: () => Promise<unknown>) {
    setError('');
    setBusy(true);
    void operation()
      .then(() => refresh())
      .catch((reason) => {
        const details = toApiServiceError(reason).data as { error?: { code?: string } } | undefined;
        setError(details?.error?.code || 'automation_unavailable');
      })
      .finally(() => setBusy(false));
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft) return;
    execute(async () => {
      const { title, prompt, model, workspace_id, target_session_id, web_search, timing, enabled } =
        draft;
      const path = draft.id ? `/api/automations/${draft.id}` : '/api/automations';
      const timingChanged =
        JSON.stringify(tasks.find((task) => task.id === draft.id)?.timing) !==
        JSON.stringify(timing);
      await requestChange(path, draft.id ? 'PATCH' : 'POST', {
        title,
        prompt,
        model,
        workspace_id,
        target_session_id,
        web_search,
        enabled,
        ...(timingChanged ? { timing } : {}),
      });
      setDraft(null);
    });
  }

  const localeDate = (value: string) =>
    new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' }).format(
      new Date(value)
    );
  const showChat = (run: Run) =>
    run.session_id && (
      <button type="button" onClick={() => onOpenChat(run.session_id!)}>
        {t('automations.openChat')}
      </button>
    );

  return (
    <section className="minds-page automation-page">
      <div className="minds-toolbar">
        <div>
          <h1>{t('automations.title')}</h1>
        </div>
        <button
          type="button"
          disabled={busy || !textModels.length}
          onClick={() => {
            setDraft({
              id: '',
              title: '',
              prompt: '',
              model: textModels.some(({ id }) => id === selectedModel)
                ? selectedModel
                : textModels[0]?.id || '',
              timing: initialTiming('daily'),
              enabled: true,
              web_search: false,
              workspace_id: null,
              target_session_id: null,
              next_run_at: null,
              last_run: null,
            });
          }}
        >
          {t('automations.add')}
        </button>
      </div>
      {error && (
        <p role="alert">
          {t(`automations.errors.${error}`, {
            defaultValue: t('automations.errors.automation_unavailable'),
          })}
        </p>
      )}
      {proposalId && /^[a-f0-9]{32}$/.test(proposalId) && (
        <AutomationReview
          key={proposalId}
          id={proposalId}
          models={models}
          projects={projects}
          sessions={webSessions}
          onApplied={refresh}
        />
      )}
      {draft && (
        <form onSubmit={save} className="automation-form">
          <label>
            {t('automations.name')}
            <input
              required
              maxLength={120}
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            />
          </label>
          <label className="automation-full">
            {t('automations.prompt')}
            <textarea
              required
              rows={4}
              maxLength={12000}
              value={draft.prompt}
              onChange={(e) => setDraft({ ...draft, prompt: e.target.value })}
            />
          </label>
          <label>
            {t('automations.model')}
            <select
              required
              value={draft.model}
              onChange={(e) => setDraft({ ...draft, model: e.target.value })}
            >
              {!textModels.some(({ id }) => id === draft.model) && (
                <option value={draft.model}>{draft.model}</option>
              )}
              {textModels.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.titleKey ? t(model.titleKey) : model.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t('automations.destination')}
            <select
              value={
                draft.target_session_id
                  ? `chat:${draft.target_session_id}`
                  : draft.workspace_id
                    ? `project:${draft.workspace_id}`
                    : ''
              }
              onChange={(e) => {
                const value = e.target.value;
                setDraft({
                  ...draft,
                  target_session_id: value.startsWith('chat:') ? value.slice(5) : null,
                  workspace_id: value.startsWith('project:') ? value.slice(8) : null,
                });
              }}
            >
              <option value="">{t('automations.newChat')}</option>
              {draft.target_session_id &&
                !webSessions.some(({ session_id }) => draft.target_session_id === session_id) && (
                  <option value={`chat:${draft.target_session_id}`}>
                    {t('automations.currentTarget')}
                  </option>
                )}
              {draft.workspace_id && !projects.some(({ id }) => draft.workspace_id === id) && (
                <option value={`project:${draft.workspace_id}`}>
                  {t('automations.currentTarget')}
                </option>
              )}
              {projects.length > 0 && (
                <optgroup label={t('projects.title')}>
                  {projects.map((project) => (
                    <option key={project.id} value={`project:${project.id}`}>
                      {project.name}
                    </option>
                  ))}
                </optgroup>
              )}
              {webSessions.length > 0 && (
                <optgroup label={t('rail.yourChats')}>
                  {webSessions.map((session) => (
                    <option key={session.session_id} value={`chat:${session.session_id}`}>
                      {session.title || t('rail.untitled')}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </label>
          <TimingEditor timing={draft.timing} update={(timing) => setDraft({ ...draft, timing })} />
          <label className="automation-check">
            <input
              type="checkbox"
              checked={draft.web_search}
              onChange={(e) => setDraft({ ...draft, web_search: e.target.checked })}
            />
            {t('automations.webSearch')}
          </label>
          <div className="automation-actions automation-full">
            <button type="submit" disabled={busy}>
              {t('projects.save')}
            </button>
            <button type="button" onClick={() => setDraft(null)}>
              {t('projects.cancel')}
            </button>
          </div>
        </form>
      )}
      {loading && <p role="status">{t('common.loading')}</p>}
      {!loading && !tasks.length && !draft && <p>{t('automations.empty')}</p>}
      <div className="automation-list">
        {tasks.map((task) => (
          <article key={task.id} className="automation-task">
            <h2>{task.title}</h2>
            <p>
              {task.next_run_at
                ? t('automations.nextRun', { time: localeDate(task.next_run_at) })
                : t(task.enabled ? 'automations.ended' : 'automations.paused')}
            </p>
            {task.last_run && <p>{t(`automations.status.${task.last_run.status}`)}</p>}
            {remove === task.id ? (
              <div className="automation-actions">
                <span>{t('automations.confirmDelete')}</span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    execute(async () => {
                      await requestChange(`/api/automations/${task.id}`, 'DELETE');
                      if (receiptTask === task.id) setReceiptTask(null);
                      setRemove(null);
                    })
                  }
                >
                  {t('rail.delete')}
                </button>
                <button type="button" onClick={() => setRemove(null)}>
                  {t('projects.cancel')}
                </button>
              </div>
            ) : (
              <div className="automation-actions">
                <button
                  type="button"
                  disabled={busy || ['running', 'queued'].includes(task.last_run?.status || '')}
                  onClick={() =>
                    execute(() => requestChange(`/api/automations/${task.id}/runs`, 'POST'))
                  }
                >
                  {t('automations.runNow')}
                </button>
                <button type="button" onClick={() => setDraft(task)}>
                  {t('automations.edit')}
                </button>
                <button
                  type="button"
                  disabled={busy || (task.enabled && !task.next_run_at)}
                  onClick={() =>
                    execute(() =>
                      requestChange(`/api/automations/${task.id}`, 'PATCH', {
                        enabled: !task.enabled,
                      })
                    )
                  }
                >
                  {t(task.enabled ? 'automations.pause' : 'automations.resume')}
                </button>
                <button
                  type="button"
                  aria-expanded={receiptTask === task.id}
                  onClick={() => {
                    setReceipts([]);
                    setReceiptTask(receiptTask === task.id ? null : task.id);
                  }}
                >
                  {t('automations.history')}
                </button>
                <button type="button" onClick={() => setRemove(task.id)}>
                  {t('rail.delete')}
                </button>
              </div>
            )}
            {receiptTask === task.id && (
              <div className="automation-history">
                {receipts.length ? (
                  receipts.map((run) => (
                    <div key={run.id} className="automation-actions">
                      <time dateTime={run.queued_at}>{localeDate(run.queued_at)}</time>
                      <span>{t(`automations.status.${run.status}`)}</span>
                      {run.error && (
                        <span>
                          {t(`automations.errors.${run.error}`, {
                            defaultValue: t('automations.status.failed'),
                          })}
                        </span>
                      )}
                      {showChat(run)}
                    </div>
                  ))
                ) : (
                  <p>{t('automations.noRuns')}</p>
                )}
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

export default function AutomationPage(props: Props) {
  const { t } = useTranslation();
  const { isAuthenticated, user } = useAuth();
  if (!isAuthenticated || !user) {
    return (
      <section className="minds-page automation-page">
        <h1>{t('automations.title')}</h1>
        <button type="button" onClick={props.onOpenAuth}>
          {t('automations.signIn')}
        </button>
      </section>
    );
  }
  return <AutomationList key={user.id} {...props} />;
}
