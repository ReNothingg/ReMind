import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../context/AuthContext';
import { fetchApi, toApiServiceError, writeApiJson as write } from '../../services/api/transport';
import SkillLibrary from './SkillLibrary';
import '../automations/automation.css';

type Manifest = {
  id: string;
  name: string;
  version: string;
  description: string;
  instructions: string;
  skills: string[];
};

type Builtin = {
  id: string;
  title_key: string | null;
  description_key: string | null;
  enabled: boolean;
};
type Custom = Manifest & { kind: 'custom'; enabled: boolean };
type Catalog = { builtins: Builtin[]; custom: Custom[] };
type Draft = { manifest: Manifest; existing: boolean };

const newManifest = (): Manifest => ({
  id: '',
  name: '',
  version: '1.0.0',
  description: '',
  instructions: '',
  skills: [],
});

function isManifestShape(value: unknown): value is Manifest {
  if (!value || typeof value !== 'object' || Object.keys(value).length !== 6) return false;
  const manifest = value as Partial<Manifest>;
  return (
    ['id', 'name', 'version', 'description', 'instructions'].every(
      (key) => typeof manifest[key as keyof Manifest] === 'string'
    ) &&
    Array.isArray(manifest.skills) &&
    manifest.skills.every((skill) => typeof skill === 'string')
  );
}

function InstalledPlugins() {
  const { t } = useTranslation();
  const [data, setData] = useState<Catalog>({ builtins: [], custom: [] });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [remove, setRemove] = useState<string | null>(null);
  const [section, setSection] = useState<'custom' | 'builtins' | 'skills'>('builtins');
  const upload = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchApi<Catalog>('/api/plugins', { signal: controller.signal })
      .then((catalog) => {
        if (!controller.signal.aborted) setData(catalog);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError('plugin_unavailable');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  function execute(action: () => Promise<void>) {
    setError('');
    setBusy(true);
    void action()
      .catch((reason) => {
        const data = toApiServiceError(reason).data as { error?: { code?: string } } | undefined;
        setError(data?.error?.code || 'plugin_unavailable');
      })
      .finally(() => setBusy(false));
  }

  async function loadManifest(file: File) {
    setError('');
    try {
      if (file.size > 25000) throw new Error();
      const manifest: unknown = JSON.parse(await file.text());
      if (!isManifestShape(manifest)) throw new Error();
      const { id, name, version, description, instructions, skills } = manifest;
      setDraft({
        existing: false,
        manifest: { id, name, version, description, instructions, skills },
      });
      setSection('custom');
    } catch {
      setError('plugin_invalid_manifest');
    }
  }

  function update(patch: Partial<Manifest>) {
    setDraft((current) => current && { ...current, manifest: { ...current.manifest, ...patch } });
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft) return;
    execute(async () => {
      const { existing, manifest } = draft;
      const result = existing
        ? await write<{ plugin: Custom }>(
            `/api/plugins/${encodeURIComponent(manifest.id)}`,
            'PATCH',
            { manifest }
          )
        : await write<{ plugin: Custom }>('/api/plugins', 'POST', manifest);
      setData((current) => ({
        ...current,
        custom: existing
          ? current.custom.map((item) => (item.id === manifest.id ? result.plugin : item))
          : [...current.custom, result.plugin],
      }));
      setDraft(null);
    });
  }

  const skillTitle = (skill: Builtin) => t(skill.title_key || `composer.tools.${skill.id}`);
  const enabledLabel = (enabled: boolean) => t(enabled ? 'plugins.disable' : 'plugins.enable');
  return (
    <section className="minds-page automation-page">
      <div className="minds-toolbar">
        <h1>{t('plugins.title')}</h1>
        {section !== 'skills' && (
          <div className="automation-actions">
            <input
              type="file"
              accept=".json,application/json"
              ref={upload}
              hidden
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                event.currentTarget.value = '';
                if (file) void loadManifest(file);
              }}
            />
            <button type="button" disabled={busy} onClick={() => upload.current?.click()}>
              {t('plugins.import')}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setDraft({ manifest: newManifest(), existing: false });
                setSection('custom');
              }}
            >
              {t('plugins.add')}
            </button>
          </div>
        )}
      </div>
      <div className="automation-actions">
        <button
          type="button"
          aria-pressed={section === 'builtins'}
          onClick={() => setSection('builtins')}
        >
          {t('plugins.builtins')}
        </button>
        <button
          type="button"
          aria-pressed={section === 'custom'}
          onClick={() => setSection('custom')}
        >
          {t('plugins.custom')}
        </button>
        <button
          type="button"
          aria-pressed={section === 'skills'}
          onClick={() => setSection('skills')}
        >
          {t('skillLibrary.title')}
        </button>
      </div>
      {section !== 'skills' && error && (
        <p role="alert">
          {t(`plugins.errors.${error}`, { defaultValue: t('plugins.errors.plugin_unavailable') })}
        </p>
      )}
      {section !== 'skills' && loading && <p role="status">{t('common.loading')}</p>}
      {section === 'skills' && <SkillLibrary />}
      {section === 'builtins' && (
        <div className="automation-list agent-plugin-grid">
          {data.builtins.map((skill) => (
            <article className="automation-task" key={skill.id}>
              <h2>{skillTitle(skill)}</h2>
              <p>{t(skill.description_key || `composer.tools.${skill.id}Description`)}</p>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  execute(async () => {
                    const { enabled } = await write<{ enabled: boolean }>(
                      `/api/plugins/builtin/${encodeURIComponent(skill.id)}`,
                      'PUT',
                      { enabled: !skill.enabled }
                    );
                    setData((current) => ({
                      ...current,
                      builtins: current.builtins.map((item) =>
                        item.id === skill.id ? { ...item, enabled } : item
                      ),
                    }));
                  })
                }
              >
                {enabledLabel(skill.enabled)}
              </button>
            </article>
          ))}
        </div>
      )}
      {section === 'custom' && (
        <div className="automation-list">
          {draft && (
            <form className="automation-form" onSubmit={save}>
              <label>
                {t('plugins.name')}
                <input
                  required
                  maxLength={100}
                  value={draft.manifest.name}
                  onChange={(e) => update({ name: e.target.value })}
                />
              </label>
              <label>
                {t('plugins.id')}
                <input
                  required
                  dir="ltr"
                  pattern="[a-z][a-z0-9\-]{2,63}"
                  maxLength={64}
                  readOnly={draft.existing}
                  value={draft.manifest.id}
                  onChange={(e) => update({ id: e.target.value })}
                />
              </label>
              <label>
                {t('plugins.version')}
                <input
                  required
                  dir="ltr"
                  maxLength={20}
                  value={draft.manifest.version}
                  onChange={(e) => update({ version: e.target.value })}
                />
              </label>
              <label className="automation-full">
                {t('plugins.description')}
                <textarea
                  required
                  rows={2}
                  maxLength={500}
                  value={draft.manifest.description}
                  onChange={(e) => update({ description: e.target.value })}
                />
              </label>
              <label className="automation-full">
                {t('plugins.instructions')}
                <textarea
                  required
                  rows={5}
                  maxLength={4000}
                  value={draft.manifest.instructions}
                  onChange={(e) => update({ instructions: e.target.value })}
                />
              </label>
              <fieldset className="automation-weekdays automation-full">
                <legend>{t('plugins.requires')}</legend>
                {data.builtins.map((skill) => (
                  <label key={skill.id}>
                    <input
                      type="checkbox"
                      checked={draft.manifest.skills.includes(skill.id)}
                      onChange={(e) =>
                        update({
                          skills: e.target.checked
                            ? [...draft.manifest.skills, skill.id]
                            : draft.manifest.skills.filter((id) => id !== skill.id),
                        })
                      }
                    />
                    {skillTitle(skill)}
                  </label>
                ))}
              </fieldset>
              <div className="automation-actions automation-full">
                <button type="submit" disabled={busy}>
                  {t(draft.existing ? 'projects.save' : 'plugins.install')}
                </button>
                <button type="button" onClick={() => setDraft(null)}>
                  {t('projects.cancel')}
                </button>
              </div>
            </form>
          )}
          {!draft && !data.custom.length && !loading && <p>{t('plugins.empty')}</p>}
          {data.custom.map((plugin) => {
            const { kind: _kind, enabled, ...manifest } = plugin;
            const url = `/api/plugins/${encodeURIComponent(manifest.id)}`;
            return (
              <article className="automation-task" key={manifest.id}>
                <h2>{manifest.name}</h2>
                <p>{manifest.description}</p>
                {manifest.skills.length > 0 && (
                  <ul className="automation-actions agent-plugin-skills">
                    {manifest.skills.map((id) => {
                      const skill = data.builtins.find((item) => item.id === id);
                      return <li key={id}>{skill ? skillTitle(skill) : id}</li>;
                    })}
                  </ul>
                )}
                {remove === manifest.id ? (
                  <div className="automation-actions">
                    <span>{t('plugins.confirmDelete')}</span>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() =>
                        execute(async () => {
                          await write(url, 'DELETE');
                          setData((current) => ({
                            ...current,
                            custom: current.custom.filter((item) => item.id !== manifest.id),
                          }));
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
                      disabled={busy}
                      onClick={() =>
                        execute(async () => {
                          const result = await write<{ plugin: Custom }>(url, 'PATCH', {
                            enabled: !enabled,
                          });
                          setData((current) => ({
                            ...current,
                            custom: current.custom.map((item) =>
                              item.id === manifest.id ? result.plugin : item
                            ),
                          }));
                        })
                      }
                    >
                      {enabledLabel(enabled)}
                    </button>
                    <button type="button" onClick={() => setDraft({ manifest, existing: true })}>
                      {t('automations.edit')}
                    </button>
                    <button type="button" onClick={() => setRemove(manifest.id)}>
                      {t('rail.delete')}
                    </button>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

export default function PluginsPage({ onOpenAuth }: { onOpenAuth: () => void }) {
  const { t } = useTranslation();
  const { isAuthenticated, user } = useAuth();
  if (!isAuthenticated || !user) {
    return (
      <section className="minds-page automation-page">
        <h1>{t('plugins.title')}</h1>
        <button type="button" onClick={onOpenAuth}>
          {t('plugins.signIn')}
        </button>
      </section>
    );
  }
  return <InstalledPlugins key={user.id} />;
}
