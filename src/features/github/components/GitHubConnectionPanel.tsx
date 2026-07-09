import { ShieldCheck } from 'lucide-react';
import type { GitHubInstallation, GitHubStatus } from '../../../services/api';
import { cn } from '../../../utils/cn';
import type { Translate } from '../githubPresentation';

type GitHubConnectionPanelProps = {
    installations: GitHubInstallation[];
    onSelectInstallation: (installationId: number) => void;
    selectedInstallationId: number | null;
    status: GitHubStatus | null;
    t: Translate;
};

export function GitHubConnectionPanel({
    installations,
    onSelectInstallation,
    selectedInstallationId,
    status,
    t,
}: GitHubConnectionPanelProps) {
    const isConnected = installations.length > 0;

    return (
        <section className="github-panel github-panel-connection">
            <div className="github-panel-head">
                <div>
                    <h2>{t('github.connection.title')}</h2>
                    <p>{status?.app?.name || t('github.connection.appFallback')}</p>
                </div>
                <span className={cn('github-status-pill', isConnected && 'is-ready')}>
                    {isConnected ? t('github.connection.ready') : t('github.connection.waiting')}
                </span>
            </div>

            {isConnected ? (
                <div className="github-installation-list">
                    {installations.map((installation) => (
                        <button
                            key={installation.installation_id}
                            type="button"
                            className={cn(
                                'github-installation-item',
                                selectedInstallationId === installation.installation_id && 'active'
                            )}
                            onClick={() => onSelectInstallation(installation.installation_id)}
                        >
                            <span className="github-installation-avatar" aria-hidden="true">
                                {installation.account_avatar_url ? (
                                    <img src={installation.account_avatar_url} alt="" />
                                ) : (
                                    <ShieldCheck size={17} />
                                )}
                            </span>
                            <span>
                                <strong>{installation.account_login}</strong>
                                <small>
                                    {installation.repository_selection === 'selected'
                                        ? t('github.connection.selectedRepos')
                                        : t('github.connection.allRepos')}
                                </small>
                            </span>
                        </button>
                    ))}
                </div>
            ) : (
                <div className="github-empty-state">
                    <ShieldCheck size={22} aria-hidden="true" />
                    <span>{t('github.connection.empty')}</span>
                </div>
            )}
        </section>
    );
}
