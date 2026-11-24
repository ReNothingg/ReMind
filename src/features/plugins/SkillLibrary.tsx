import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { FileUp } from 'lucide-react';
import { fetchApi, toApiServiceError, writeApiJson } from '../../services/api/transport';
import {
  maxArchiveBytes,
  maxMarkdownBytes,
  parseSkillMarkdown,
  personalSkillEndpoint,
  type ImportedSkill,
  type SkillDocument,
} from './skillPackage';
import './skill-library.css';

type SkillInspection = ImportedSkill & { body: string; resources: string[]; scripts?: string[] };
type ArchivePreview = { markdown: string; resources: Record<string, string> };
type Library = { skills: ImportedSkill[] };
type StoredSkill = { skill: ImportedSkill };

function errorCode(reason: unknown, fallback: string) {
  const error = toApiServiceError(reason);
  const response = error.data as { error?: { code?: string } } | undefined;
  const code = response?.error?.code || error.message;
  if (error.status === 413) return 'skill_package_too_large';
  return /^skill_[a-z_]+$/.test(code) ? code : fallback;
}

export default function SkillLibrary({ workspaceId }: { workspaceId?: string }) {
  const { t } = useTranslation();
  const fileInput = useRef<HTMLInputElement>(null);
  const importId = useId();
  const [skills, setSkills] = useState<ImportedSkill[]>([]);
  const [preview, setPreview] = useState<SkillDocument | null>(null);
  const [inspection, setInspection] = useState<SkillInspection | null>(null);
  const [source, setSource] = useState('');
  const [confirmRemove, setConfirmRemove] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');
  const endpoint = workspaceId
    ? `/api/workspaces/${encodeURIComponent(workspaceId)}/skills`
    : personalSkillEndpoint;
  const previewMembers = Object.entries(preview?.resources || {});
  const previewReferences = previewMembers.filter(([path]) => !path.startsWith('scripts/'));
  const previewScripts = previewMembers.filter(([path]) => path.startsWith('scripts/'));

  useEffect(() => {
    const controller = new AbortController();
    fetchApi<Library>(endpoint, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setSkills(result.skills);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(errorCode(reason, 'skill_library_unavailable'));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [endpoint]);

  async function run(action: () => Promise<void>, fallback = 'skill_library_unavailable') {
    if (busy) return;
    setBusy(true);
    setFeedback('');
    setError('');
    try {
      await action();
    } catch (reason) {
      setError(errorCode(reason, fallback));
    } finally {
      setBusy(false);
    }
  }

  function replaceInList(skill: ImportedSkill) {
    setSkills((current) =>
      [...current.filter((item) => item.id !== skill.id), skill].sort((a, b) =>
        a.name.localeCompare(b.name)
      )
    );
  }

  function importFile(file: File) {
    void run(async () => {
      setPreview(null);
      if (/\.(zip|skill)$/i.test(file.name)) {
        if (file.size > maxArchiveBytes) throw new Error('skill_package_too_large');
        const body = new FormData();
        body.append('package', file);
        const unpacked = await fetchApi<ArchivePreview>(personalSkillEndpoint + '/unpack', {
          method: 'POST',
          body,
        });
        setPreview(await parseSkillMarkdown(unpacked.markdown, unpacked.resources));
      } else {
        if (file.size > maxMarkdownBytes) throw new Error('skill_package_too_large');
        const raw = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
        setPreview(await parseSkillMarkdown(raw));
      }
    }, 'skill_invalid_document');
  }

  function previewPasted(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(async () => {
      setPreview(null);
      setPreview(await parseSkillMarkdown(source));
    }, 'skill_invalid_document');
  }

  function install() {
    if (!preview) return;
    void run(async () => {
      const replace = skills.some((item) => item.name === preview.name);
      const { skill } = await writeApiJson<StoredSkill>(endpoint, 'POST', {
        document: preview,
        replace,
      });
      replaceInList(skill);
      setPreview(null);
      setSource('');
      setInspection(null);
      setFeedback(t(replace ? 'skillLibrary.replaced' : 'skillLibrary.installed'));
    });
  }

  return (
    <div className="skill-library">
      <div className="skill-library-import">
        <p>{t(workspaceId ? 'skillLibrary.projectHint' : 'skillLibrary.personalHint')}</p>
        <input
          ref={fileInput}
          type="file"
          accept=".md,.zip,.skill"
          hidden
          onChange={(event) => {
            const sourceFile = event.currentTarget.files?.[0];
            event.currentTarget.value = '';
            if (sourceFile) importFile(sourceFile);
          }}
        />
        <button type="button" disabled={busy} onClick={() => fileInput.current?.click()}>
          <FileUp size={16} aria-hidden="true" />
          {t('skillLibrary.upload')}
        </button>
      </div>
      <details className="skill-library-paste">
        <summary>{t('skillLibrary.paste')}</summary>
        <form onSubmit={previewPasted}>
          <label htmlFor={importId}>{t('skillLibrary.markdown')}</label>
          <textarea
            id={importId}
            value={source}
            rows={7}
            disabled={busy}
            maxLength={maxMarkdownBytes}
            onChange={(event) => setSource(event.target.value)}
          />
          <button type="submit" disabled={busy || !source.trim()}>
            {t('skillLibrary.preview')}
          </button>
        </form>
      </details>
      {error && (
        <p role="alert">
          {t('skillLibrary.errors.' + error, {
            defaultValue: t('skillLibrary.errors.skill_library_unavailable'),
          })}
        </p>
      )}
      {feedback && <p role="status">{feedback}</p>}
      {preview && (
        <section className="skill-library-draft">
          <h3>{preview.name}</h3>
          <p>{preview.description}</p>
          {preview.compatibility && <p>{preview.compatibility}</p>}
          <pre>{preview.body}</pre>
          {previewReferences.length > 0 && (
            <ul className="skill-library-resources">
              {previewReferences.map(([path]) => (
                <li key={path}>
                  <code dir="ltr">{path}</code>
                </li>
              ))}
            </ul>
          )}
          {previewScripts.length > 0 && (
            <div className="skill-library-scripts">
              <h4>{t('skillLibrary.scripts')}</h4>
              <p>{t('skillLibrary.scriptSettings')}</p>
              {previewScripts.map(([path, script]) => (
                <details key={path}>
                  <summary><code dir="ltr">{path}</code></summary>
                  <pre dir="ltr">{script}</pre>
                </details>
              ))}
            </div>
          )}
          <div className="skill-library-actions">
            <button type="button" disabled={busy || loading} onClick={install}>
              {t(
                skills.some(({ name }) => name === preview.name)
                  ? 'skillLibrary.replace'
                  : 'skillLibrary.install'
              )}
            </button>
            <button type="button" disabled={busy} onClick={() => setPreview(null)}>
              {t('projects.cancel')}
            </button>
          </div>
        </section>
      )}
      {loading ? (
        <p role="status">{t('common.loading')}</p>
      ) : (
        !skills.length && <p>{t('skillLibrary.empty')}</p>
      )}
      {skills.length > 0 && (
        <ul className="skill-library-list">
          {skills.map((skill) => (
            <li key={skill.id}>
              <article>
                <h3>{skill.name}</h3>
                <p>{skill.description}</p>
                {skill.enabled && skill.userInvocable && <code dir="ltr">/{skill.name}</code>}
                <div className="skill-library-actions">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      if (inspection?.id === skill.id) setInspection(null);
                      else
                        void run(async () => {
                          const result = await fetchApi<{ skill: SkillInspection }>(
                            endpoint + '/' + skill.id
                          );
                          setInspection(result.skill);
                        });
                    }}
                  >
                    {t('skillLibrary.instructions')}
                  </button>
                  <button
                    type="button"
                    aria-pressed={skill.enabled}
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        const result = await writeApiJson<StoredSkill>(
                          endpoint + '/' + skill.id,
                          'PATCH',
                          { enabled: !skill.enabled }
                        );
                        replaceInList(result.skill);
                      })
                    }
                  >
                    {t(skill.enabled ? 'plugins.disable' : 'plugins.enable')}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => {
                      if (confirmRemove !== skill.id) {
                        setConfirmRemove(skill.id);
                        return;
                      }
                      void run(async () => {
                        await writeApiJson(endpoint + '/' + skill.id, 'DELETE');
                        setSkills((items) => items.filter(({ id }) => id !== skill.id));
                        if (inspection?.id === skill.id) setInspection(null);
                        setConfirmRemove('');
                      });
                    }}
                  >
                    {t(confirmRemove === skill.id ? 'skillLibrary.confirmRemove' : 'rail.delete')}
                  </button>
                  {confirmRemove === skill.id && (
                    <button type="button" onClick={() => setConfirmRemove('')}>
                      {t('projects.cancel')}
                    </button>
                  )}
                </div>
                {inspection?.id === skill.id && (
                  <div className="skill-library-draft">
                    <pre>{inspection.body}</pre>
                    {inspection.resources.length > 0 && (
                      <ul className="skill-library-resources">
                        {inspection.resources.map((path) => (
                          <li key={path}>
                            <code dir="ltr">{path}</code>
                          </li>
                        ))}
                      </ul>
                    )}
                    {!!inspection.scripts?.length && (
                      <div className="skill-library-scripts">
                        <h4>{t('skillLibrary.scripts')}</h4>
                        <ul className="skill-library-resources">
                          {inspection.scripts.map((path) => (
                            <li key={path}><code dir="ltr">{path}</code></li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </article>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
