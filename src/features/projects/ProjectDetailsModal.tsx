import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import ModalShell from '../../components/UI/ModalShell';
import { fetchApi, toApiServiceError, writeApiJson } from '../../services/api/transport';
import { CHAT_UPLOAD_EXTENSIONS } from '../../utils/constants';
import SkillLibrary from '../plugins/SkillLibrary';
import type { Project } from './useProjects';
import './project-details.css';

const acceptedFiles = [...CHAT_UPLOAD_EXTENSIONS, 'pdf']
  .map((extension) => `.${extension}`)
  .join(',');

type ProjectFile = {
  id: string;
  name: string;
  size: number;
};

type ProjectDetails = Project & {
  instructions: string;
  files: ProjectFile[];
};

export default function ProjectDetailsModal({
  project,
  onClose,
}: {
  project: Project;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation();
  const titleId = useId();
  const upload = useRef<HTMLInputElement>(null);
  const [details, setDetails] = useState<ProjectDetails | null>(null);
  const [instructions, setInstructions] = useState('');
  const [removeId, setRemoveId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [skillsOpen, setSkillsOpen] = useState(false);
  const endpoint = `/api/workspaces/${encodeURIComponent(project.id)}`;

  function messageCode(reason: unknown) {
    const data = toApiServiceError(reason).data as { error?: { code?: string } } | undefined;
    return data?.error?.code || 'workspace_runtime_unavailable';
  }

  useEffect(() => {
    const controller = new AbortController();
    fetchApi<ProjectDetails>(endpoint, { signal: controller.signal })
      .then((value) => {
        if (controller.signal.aborted) return;
        setDetails(value);
        setInstructions(value.instructions);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(messageCode(reason));
      });
    return () => controller.abort();
  }, [endpoint]);

  async function act(task: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError('');
    setSaved(false);
    try {
      await task();
    } catch (reason) {
      setError(messageCode(reason));
    } finally {
      setBusy(false);
    }
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void act(async () => {
      const result = await writeApiJson<{ instructions: string }>(
        `${endpoint}/instructions`,
        'PUT',
        { instructions }
      );
      setDetails((current) => current && { ...current, instructions: result.instructions });
      setInstructions(result.instructions);
      setSaved(true);
    });
  }

  function addFiles(files: FileList) {
    const body = new FormData();
    Array.from(files).forEach((file) => body.append('files', file));
    void act(async () => {
      const result = await fetchApi<{ files: ProjectFile[] }>(`${endpoint}/files`, {
        method: 'POST',
        body,
      });
      setDetails(
        (current) => current && { ...current, files: [...current.files, ...result.files] }
      );
    });
  }

  return (
    <ModalShell
      ariaLabelledBy={titleId}
      className="project-details-overlay"
      contentClassName="project-details"
      onBackdropClick={onClose}
      onRequestClose={onClose}
    >
      <header className="project-details-header">
        <h2 id={titleId}>{project.name}</h2>
        <button type="button" onClick={onClose} aria-label={t('common.close')}>
          <X size={18} aria-hidden="true" />
        </button>
      </header>
      <div className="project-details-body">
        {error && (
          <p role="alert">
            {t(`projects.errors.${error}`, { defaultValue: t('projects.failed') })}
          </p>
        )}
        {!details && !error && <p role="status">{t('common.loading')}</p>}
        {details && (
          <>
            <form className="project-details-instructions" onSubmit={save}>
              <label>
                {t('projects.instructions')}
                <textarea
                  value={instructions}
                  maxLength={65_536}
                  rows={5}
                  onChange={(event) => {
                    setInstructions(event.target.value);
                    setSaved(false);
                  }}
                  disabled={busy}
                />
              </label>
              <p>{t('projects.instructionsHint')}</p>
              <div className="project-details-actions">
                <button type="submit" disabled={busy || instructions === details.instructions}>
                  {t('projects.save')}
                </button>
                {saved && <span role="status">{t('projects.saved')}</span>}
              </div>
            </form>
            <section className="project-details-library">
              <div className="project-details-actions project-details-library-heading">
                <h3>{t('projects.files')}</h3>
                <input
                  hidden
                  type="file"
                  multiple
                  accept={acceptedFiles}
                  ref={upload}
                  onChange={(event) => {
                    const files = event.currentTarget.files;
                    if (files?.length) addFiles(files);
                    event.currentTarget.value = '';
                  }}
                />
                <button type="button" disabled={busy} onClick={() => upload.current?.click()}>
                  {t('projects.upload')}
                </button>
              </div>
              {!details.files.length && <p>{t('projects.emptyFiles')}</p>}
              <ul>
                {details.files.map((file) => {
                  const fileUrl = `${endpoint}/files/${encodeURIComponent(file.id)}`;
                  return (
                    <li key={file.id}>
                      <div className="project-details-file-name">
                        <a href={fileUrl} download={file.name}>
                          {file.name}
                        </a>
                        <small>
                          {new Intl.NumberFormat(i18n.language, {
                            style: 'unit',
                            unit: 'kilobyte',
                            maximumFractionDigits: 1,
                          }).format(file.size / 1000)}
                        </small>
                      </div>
                      {removeId === file.id ? (
                        <div className="project-details-actions">
                          <span>{t('projects.confirmFileRemove')}</span>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() =>
                              void act(async () => {
                                await writeApiJson(fileUrl, 'DELETE');
                                setDetails(
                                  (current) =>
                                    current && {
                                      ...current,
                                      files: current.files.filter(({ id }) => id !== file.id),
                                    }
                                );
                                setRemoveId(null);
                              })
                            }
                          >
                            {t('rail.delete')}
                          </button>
                          <button type="button" onClick={() => setRemoveId(null)}>
                            {t('projects.cancel')}
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => setRemoveId(file.id)}
                          aria-label={t('projects.deleteFile', { name: file.name })}
                        >
                          {t('rail.delete')}
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
            <details className="project-skill-library" onToggle={(event) => setSkillsOpen(event.currentTarget.open)}>
              <summary>{t('skillLibrary.title')}</summary>
              {skillsOpen && <SkillLibrary key={project.id} workspaceId={project.id} />}
            </details>
          </>
        )}
      </div>
    </ModalShell>
  );
}
