import { useState } from 'react';
import { ChevronLeft, ChevronRight, Download, FileText, LoaderCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { artifactDownloadUrl, checkArtifactDownload } from '../../services/downloadArtifact';
import SaveProjectArtifact, { type ArtifactProjectTarget } from '../../features/projects/SaveProjectArtifact';
import Pet from '../UI/Pet';

export default function ArtifactDownloadCard({
  path,
  filename,
  size,
  slides,
  project,
}: {
  path: string;
  filename: string;
  size?: number;
  slides?: unknown;
  project?: ArtifactProjectTarget;
}) {
  const { t, i18n } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [page, setPage] = useState(0);
  const pages: { title: string; points: string[] }[] =
    filename.toLowerCase().endsWith('.pptx') &&
    Array.isArray(slides) &&
    slides.length <= 25 &&
    slides.every(
      (slide) =>
        slide &&
        typeof slide.title === 'string' &&
        slide.title.length <= 100 &&
        Array.isArray(slide.points) &&
        slide.points.length <= 5 &&
        slide.points.every((point: unknown) => typeof point === 'string' && point.length <= 180)
    )
      ? slides
      : [];
  const slide = pages[page];
  let url = '';
  try {
    url = artifactDownloadUrl(path);
  } catch {
    url = '';
  }
  const unit = size && size >= 1048576 ? 'megabyte' : size && size >= 1024 ? 'kilobyte' : 'byte';
  const divisor = unit === 'megabyte' ? 1048576 : unit === 'kilobyte' ? 1024 : 1;
  const formattedSize =
    size && Number.isFinite(size)
      ? new Intl.NumberFormat(i18n.language, {
          style: 'unit',
          unit,
          unitDisplay: 'short',
          maximumFractionDigits: 2,
        }).format(size / divisor)
      : '';
  const download = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await checkArtifactDownload(url);
    } catch (failure) {
      setError(
        failure instanceof Error && failure.message === 'artifact_unavailable'
          ? 'unavailable'
          : 'failed'
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="artifact-download">
      <a
        className="artifact-download-card"
        href={url || undefined}
        download={filename}
        onClick={(event) => {
          if (busy || !url) {
            event.preventDefault();
            return;
          }
          void download();
        }}
        aria-disabled={busy || !url || undefined}
        aria-busy={busy || undefined}
        aria-label={t('artifactDownload.action', { name: filename })}
      >
        {filename.toLowerCase().endsWith('.pptx') ? (
          <Pet state="success" animate={false} />
        ) : (
          <FileText className="artifact-download-file-icon" aria-hidden="true" />
        )}
        <span className="artifact-download-copy">
          <span className="artifact-download-name">{filename}</span>
          <span className="artifact-download-meta">
            {formattedSize}
            {formattedSize ? ' · ' : ''}
            {t(busy ? 'artifactDownload.loading' : 'artifactDownload.label')}
          </span>
        </span>
        {busy ? (
          <LoaderCircle className="artifact-download-spinner" aria-hidden="true" />
        ) : (
          <Download aria-hidden="true" />
        )}
      </a>
      {project && <SaveProjectArtifact key={project.projectId + project.artifactPath} {...project} />}
      {slide && (
        <details className="chat-slide-outline">
          <summary>{t('slideDeck.contents')}</summary>
          <div aria-live="polite">
            <h4>{slide.title}</h4>
            {slide.points.length > 0 && (
              <ul>
                {slide.points.map((point, index) => (
                  <li key={index}>{point}</li>
                ))}
              </ul>
            )}
          </div>
          <div className="chat-slide-controls">
            <button
              type="button"
              onClick={() => setPage(page - 1)}
              disabled={!page}
              aria-label={t('slideDeck.previous')}
            >
              <ChevronLeft size={18} />
            </button>
            <span>{t('slideDeck.position', { page: page + 1, total: pages.length })}</span>
            <button
              type="button"
              onClick={() => setPage(page + 1)}
              disabled={page >= pages.length - 1}
              aria-label={t('slideDeck.next')}
            >
              <ChevronRight size={18} />
            </button>
          </div>
        </details>
      )}
      {(error || !url) && (
        <p className="artifact-download-error" role="alert">
          {t(`artifactDownload.${error || 'unavailable'}`)}
        </p>
      )}
    </div>
  );
}
