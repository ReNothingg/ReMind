import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import Pet from '../../components/UI/Pet';
import type { components } from '../../generated/openapi';
import { fetchApi, toApiServiceError, writeApiJson } from '../../services/api/transport';
import './project-changes.css';

type PatchSummary = components['schemas']['WorkspacePatchView'];

export default function WorkspacePatchCard({
  state,
  ready,
  projectId,
}: {
  state: Record<string, unknown> | undefined;
  ready: boolean;
  projectId: string;
}) {
  const { t } = useTranslation();
  const [review, setReview] = useState<PatchSummary | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const id = state?.proposal_id;
  if (typeof id !== 'string' || !/^[a-f0-9]{32}$/.test(id) || state?.workspace_id !== projectId)
    return null;
  const endpoint = `/api/workspaces/${encodeURIComponent(projectId)}/patches/${id}`;

  async function act(approve: boolean) {
    if (busy || (approve && (!review || review.applied_at))) return;
    setBusy(true);
    setError('');
    try {
      const response = approve
        ? await writeApiJson<PatchSummary>(endpoint + '/apply', 'POST')
        : await fetchApi<PatchSummary>(endpoint);
      setReview(response);
    } catch (failure) {
      const response = toApiServiceError(failure).data as { error?: { code?: string } } | undefined;
      setError(response?.error?.code || 'workspace_runtime_unavailable');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="chat-tool-panel project-patch-card">
      <h3 className="ui-pet-panel-heading">
        <Pet state={review?.applied_at ? 'success' : 'review'} animate={!ready} />
        {t('projectChanges.patchTitle')}
      </h3>
      {ready && !review && (
        <button type="button" disabled={busy} onClick={() => void act(false)}>
          {t(busy ? 'common.loading' : 'projectChanges.review')}
        </button>
      )}
      {review?.applied_at && <p role="status">{t('projectChanges.applied')}</p>}
      {review && !review.applied_at && (
        <div className="project-patch-preview">
          <ul>
            {review.changes.map(({ kind, path, destination, spreadsheet_formulas_escaped }, index) => (
              <li key={index}>
                {t('projectChanges.operations.' + kind, { path, destination })}
                {spreadsheet_formulas_escaped && <span> {t('projectChanges.formulasEscaped')}</span>}
              </li>
            ))}
          </ul>
          <pre dir="ltr">{review.patch}</pre>
          <div className="project-patch-controls">
            <button type="button" disabled={busy || error === 'workspace_patch_stale'} onClick={() => void act(true)}>
              {t(busy ? 'common.loading' : 'projectChanges.apply')}
            </button>
            <button type="button" disabled={busy} onClick={() => { setReview(null); setError(''); }}>
              {t('common.close')}
            </button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert">
          {t('projectChanges.errors.' + error, {
            defaultValue: t(`projects.errors.${error}`, { defaultValue: t('projectChanges.errors.patchFailed') }),
          })}
        </p>
      )}
    </section>
  );
}
