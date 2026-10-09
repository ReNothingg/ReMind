import { useState } from 'react';
import { Download, FileText, LoaderCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { artifactDownloadUrl, checkArtifactDownload } from '../../services/downloadArtifact';

export default function ArtifactDownloadCard({ path, filename, size }: { path: string; filename: string; size?: number }) {
    const { t, i18n } = useTranslation();
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    let url = '';
    try { url = artifactDownloadUrl(path); } catch { url = ''; }
    const unit = size && size >= 1048576 ? 'megabyte' : size && size >= 1024 ? 'kilobyte' : 'byte';
    const divisor = unit === 'megabyte' ? 1048576 : unit === 'kilobyte' ? 1024 : 1;
    const formattedSize = size && Number.isFinite(size) ? new Intl.NumberFormat(i18n.language, { style: 'unit', unit, unitDisplay: 'short', maximumFractionDigits: 2 }).format(size / divisor) : '';
    const download = async () => {
        if (busy) return;
        setBusy(true);
        setError('');
        try { await checkArtifactDownload(url); }
        catch (failure) { setError(failure instanceof Error && failure.message === 'artifact_unavailable' ? 'unavailable' : 'failed'); }
        finally { setBusy(false); }
    };
    return <div className="artifact-download">
        <a className="artifact-download-card" href={url || undefined} download={filename} onClick={event => { if (busy || !url) { event.preventDefault(); return; } void download(); }} aria-disabled={busy || !url || undefined} aria-busy={busy || undefined} aria-label={t('artifactDownload.action', { name: filename })}>
            <FileText className="artifact-download-file-icon" aria-hidden="true" />
            <span className="artifact-download-copy"><span className="artifact-download-name">{filename}</span><span className="artifact-download-meta">{formattedSize}{formattedSize ? ' · ' : ''}{t(busy ? 'artifactDownload.loading' : 'artifactDownload.label')}</span></span>
            {busy ? <LoaderCircle className="artifact-download-spinner" aria-hidden="true" /> : <Download aria-hidden="true" />}
        </a>
        {(error || !url) && <p className="artifact-download-error" role="alert">{t(`artifactDownload.${error || 'unavailable'}`)}</p>}
    </div>;
}
