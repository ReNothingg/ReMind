import { useState } from 'react';
import { Check, FolderPlus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toApiServiceError, writeApiJson } from '../../services/api/transport';
import './project-changes.css';

export type ArtifactProjectTarget = {
  projectId: string;
  sessionId: string;
  artifactPath: string;
};

export default function SaveProjectArtifact({ projectId, sessionId, artifactPath }: ArtifactProjectTarget) {
  const { t } = useTranslation();
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  async function save() {
    if (pending || saved) return;
    setPending(true);
    setError('');
    try {
      await writeApiJson(`/api/workspaces/${encodeURIComponent(projectId)}/files/from-chat`, 'POST', {
        session_id: sessionId,
        artifact_path: artifactPath,
      });
      setSaved(true);
    } catch (failure) {
      const response = toApiServiceError(failure).data as { error?: { code?: string } } | undefined;
      setError(response?.error?.code || 'workspace_runtime_unavailable');
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="project-artifact-action">
      <button type="button" disabled={pending || saved} onClick={() => void save()}>
        {saved ? <Check size={16} aria-hidden="true" /> : <FolderPlus size={16} aria-hidden="true" />}
        {t(saved ? 'projectChanges.savedArtifact' : pending ? 'common.loading' : 'projectChanges.saveArtifact')}
      </button>
      {error && (
        <p role="alert">
          {t('projectChanges.errors.' + error, {
            defaultValue: t(`projects.errors.${error}`, { defaultValue: t('projectChanges.errors.artifactSave') }),
          })}
        </p>
      )}
    </div>
  );
}
