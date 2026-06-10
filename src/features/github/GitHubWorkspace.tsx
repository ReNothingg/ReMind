import { FormEvent, useCallback, useDeferredValue, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
    AlertTriangle,
    CheckCircle2,
    ExternalLink,
    GitBranch,
    Github,
    GitPullRequest,
    Loader2,
    PlugZap,
    RefreshCw,
    Search,
    ShieldCheck,
} from 'lucide-react';
import {
    apiService,
    type GitHubAgentActivity,
    type GitHubAgentTask,
    type GitHubInstallation,
    type GitHubRepository,
    type GitHubStatus,
} from '../../services/api';
import { cn } from '../../utils/cn';

type GitHubWorkspaceProps = {
    isAuthenticated: boolean;
    onOpenAuth: () => void;
};

type LoadState = 'idle' | 'loading' | 'error';
const EMPTY_INSTALLATIONS: GitHubInstallation[] = [];
const EMPTY_REPOSITORIES: GitHubRepository[] = [];

function formatCount(value: number | undefined, fallback = 0): string {
    return String(Number.isFinite(value) ? value : fallback);
}

function taskStatusLabel(t: ReturnType<typeof useTranslation>['t'], status?: string): string {
    switch (status) {
        case 'planning':
            return t('github.taskStatus.planning');
        case 'planned':
            return t('github.taskStatus.planned');
        case 'running':
            return t('github.taskStatus.running');
        case 'pull_request_opened':
            return t('github.taskStatus.pullRequestOpened');
        case 'completed_no_changes':
            return t('github.taskStatus.completedNoChanges');
        case 'error':
            return t('github.taskStatus.error');
        default:
            return t('github.taskStatus.idle');
    }
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function asString(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

function asNumber(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function activityTitle(t: ReturnType<typeof useTranslation>['t'], item: GitHubAgentActivity): string {
    const code = item.code || 'unknown';
    return t(`github.activity.codes.${code}`, {
        defaultValue: t('github.activity.codes.unknown'),
    });
}

function activityDetail(t: ReturnType<typeof useTranslation>['t'], item: GitHubAgentActivity): string {
    const meta = isRecord(item.meta) ? item.meta : {};
    switch (item.code) {
        case 'repoMapLoaded':
            return t('github.activity.details.repoMapLoaded', {
                directories: formatCount(asNumber(meta.directories)),
                files: formatCount(asNumber(meta.files)),
            });
        case 'candidateFilesSelected':
        case 'plannedFilesLoaded':
        case 'fileContextLoaded':
            return t('github.activity.details.filesCount', {
                count: asNumber(meta.count) ?? 0,
            });
        case 'geminiJsonParsed':
            return t('github.activity.details.geminiJsonParsed', {
                chars: formatCount(asNumber(meta.response_chars)),
            });
        case 'geminiInvalidJson':
            return t('github.activity.details.geminiInvalidJson', {
                chars: formatCount(asNumber(meta.response_chars)),
            });
        case 'geminiRequestFailed':
        case 'editorFailed':
            return asString(meta.message);
        case 'commitCreated':
            return t('github.activity.details.commitCreated', {
                branch: asString(meta.branch),
            });
        case 'diffLoaded':
            return t('github.activity.details.diffLoaded', {
                files: formatCount(asNumber(meta.files)),
            });
        case 'noChanges':
            return asString(meta.reason);
        case 'pullRequestOpened':
            return t('github.activity.details.pullRequestOpened', {
                number: formatCount(asNumber(meta.number)),
            });
        default:
            return '';
    }
}

function activityPaths(item: GitHubAgentActivity): string[] {
    const meta = isRecord(item.meta) ? item.meta : {};
    return Array.isArray(meta.paths)
        ? meta.paths.filter((path): path is string => typeof path === 'string' && path.length > 0)
        : [];
}

function activityPreview(item: GitHubAgentActivity): string {
    const meta = isRecord(item.meta) ? item.meta : {};
    return asString(meta.response_preview);
}

function localizedAgentMessage(t: ReturnType<typeof useTranslation>['t'], value?: string | null): string {
    if (!value) {
        return '';
    }
    const fallbackMap: Record<string, string> = {
        'Prepare a focused code change in a pull request.': 'github.plan.fallbacks.summary',
        'Inspect repository map': 'github.plan.fallbacks.inspectTitle',
        'Use the selected files as the first editing context.': 'github.plan.fallbacks.inspectDetails',
        'Generate code edits': 'github.plan.fallbacks.editTitle',
        'Apply a small, reviewable change on a new branch.': 'github.plan.fallbacks.editDetails',
        'Open pull request': 'github.plan.fallbacks.prTitle',
        'Show the generated diff and create a PR against the base branch.': 'github.plan.fallbacks.prDetails',
        'The AI planner could not run; selected files are heuristic.': 'github.plan.fallbacks.plannerFallbackRisk',
        'AI editor did not return JSON edits.': 'github.errors.editorInvalidJson',
    };
    const key = fallbackMap[value];
    return key ? t(key) : value;
}

export default function GitHubWorkspace({ isAuthenticated, onOpenAuth }: GitHubWorkspaceProps) {
    const { t } = useTranslation();
    const [status, setStatus] = useState<GitHubStatus | null>(null);
    const [loadState, setLoadState] = useState<LoadState>('idle');
    const [error, setError] = useState('');
    const [selectedInstallationId, setSelectedInstallationId] = useState<number | null>(null);
    const [selectedRepoName, setSelectedRepoName] = useState('');
    const [repoSearch, setRepoSearch] = useState('');
    const deferredRepoSearch = useDeferredValue(repoSearch.trim().toLowerCase());
    const [baseBranch, setBaseBranch] = useState('');
    const [taskText, setTaskText] = useState('');
    const [activeTask, setActiveTask] = useState<GitHubAgentTask | null>(null);
    const [isPlanning, setIsPlanning] = useState(false);
    const [isRunning, setIsRunning] = useState(false);

    const installations = status?.installations ?? EMPTY_INSTALLATIONS;
    const repositories = status?.repositories ?? EMPTY_REPOSITORIES;

    const selectedRepo = useMemo(
        () => repositories.find((repo) => repo.full_name === selectedRepoName) || null,
        [repositories, selectedRepoName]
    );

    const filteredRepositories = useMemo(() => {
        if (!deferredRepoSearch) {
            return repositories;
        }
        return repositories.filter((repo) =>
            repo.full_name.toLowerCase().includes(deferredRepoSearch)
        );
    }, [deferredRepoSearch, repositories]);

    const activityItems = useMemo(() => {
        const planActivity = activeTask?.plan?.activity || [];
        const editActivity = activeTask?.edits?.activity || [];
        return [...planActivity, ...editActivity];
    }, [activeTask]);

    const visibleActivityItems = useMemo(() => {
        if (isPlanning) {
            return [
                ...activityItems,
                { code: 'planningLive', status: 'running' } satisfies GitHubAgentActivity,
            ];
        }
        if (isRunning) {
            return [
                ...activityItems,
                { code: 'runningLive', status: 'running' } satisfies GitHubAgentActivity,
            ];
        }
        return activityItems;
    }, [activityItems, isPlanning, isRunning]);

    const loadStatus = useCallback(
        async (installationId = selectedInstallationId) => {
            if (!isAuthenticated) {
                setStatus(null);
                return;
            }
            setLoadState('loading');
            setError('');
            try {
                const data = await apiService.getGitHubStatus(installationId || undefined);
                setStatus(data);
                const nextInstallationId = data.selected_installation_id || data.installations[0]?.installation_id || null;
                setSelectedInstallationId(nextInstallationId);
                const nextRepo = data.repositories.find((repo) => repo.full_name === selectedRepoName)
                    || data.repositories[0]
                    || null;
                setSelectedRepoName(nextRepo?.full_name || '');
                setBaseBranch((current) => current || nextRepo?.default_branch || '');
                setLoadState('idle');
            } catch (loadError) {
                const message = loadError instanceof Error ? loadError.message : t('github.errors.loadStatus');
                setError(message);
                setLoadState('error');
            }
        },
        [isAuthenticated, selectedInstallationId, selectedRepoName, t]
    );

    useEffect(() => {
        void loadStatus();
    }, [loadStatus]);

    useEffect(() => {
        if (selectedRepo && !baseBranch) {
            setBaseBranch(selectedRepo.default_branch);
        }
    }, [baseBranch, selectedRepo]);

    const handleInstallationChange = (installationId: number) => {
        setSelectedInstallationId(installationId);
        setSelectedRepoName('');
        setBaseBranch('');
        setActiveTask(null);
        void loadStatus(installationId);
    };

    const handleRepoSelect = (repo: GitHubRepository) => {
        setSelectedRepoName(repo.full_name);
        setBaseBranch(repo.default_branch);
        setActiveTask(null);
    };

    const handleConnect = () => {
        const connectUrl = status?.urls?.connect || '/auth/github/login?after=install';
        window.location.assign(connectUrl);
    };

    const handleRefresh = () => {
        void loadStatus();
    };

    const handlePlan = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!selectedInstallationId || !selectedRepoName || !baseBranch || !taskText.trim()) {
            return;
        }
        setIsPlanning(true);
        setError('');
        setActiveTask(null);
        try {
            const plannedTask = await apiService.createGitHubPlan({
                installation_id: selectedInstallationId,
                repo_full_name: selectedRepoName,
                base_branch: baseBranch,
                task: taskText.trim(),
            });
            setActiveTask(plannedTask);
        } catch (planError) {
            setError(planError instanceof Error
                ? localizedAgentMessage(t, planError.message)
                : t('github.errors.plan'));
        } finally {
            setIsPlanning(false);
        }
    };

    const handleRun = async () => {
        if (!activeTask?.id) {
            return;
        }
        const taskId = activeTask.id;
        setIsRunning(true);
        setError('');
        try {
            const result = await apiService.runGitHubTask(taskId);
            setActiveTask(result);
            void loadStatus();
        } catch (runError) {
            setError(runError instanceof Error
                ? localizedAgentMessage(t, runError.message)
                : t('github.errors.run'));
            try {
                const latestTask = await apiService.getGitHubTask(taskId);
                setActiveTask(latestTask);
            } catch {
                // Keep the visible API error when task refresh also fails.
            }
        } finally {
            setIsRunning(false);
        }
    };

    if (!isAuthenticated) {
        return (
            <section className="github-workspace">
                <div className="github-auth-required">
                    <Github size={34} aria-hidden="true" />
                    <h1>{t('github.authRequiredTitle')}</h1>
                    <button type="button" className="github-primary-action" onClick={onOpenAuth}>
                        {t('auth.login')}
                    </button>
                </div>
            </section>
        );
    }

    return (
        <section className="github-workspace">
            <div className="github-toolbar">
                <div>
                    <div className="github-title-row">
                        <Github size={30} aria-hidden="true" />
                        <h1>{t('github.title')}</h1>
                    </div>
                    <p>{t('github.subtitle')}</p>
                </div>
                <div className="github-toolbar-actions">
                    <button
                        type="button"
                        className="github-secondary-action"
                        onClick={handleRefresh}
                        disabled={loadState === 'loading'}
                    >
                        <RefreshCw size={16} className={cn(loadState === 'loading' && 'animate-spin')} />
                        {t('github.refresh')}
                    </button>
                    <button type="button" className="github-primary-action" onClick={handleConnect}>
                        <PlugZap size={17} />
                        {installations.length > 0 ? t('github.manageConnection') : t('github.connect')}
                    </button>
                </div>
            </div>

            {error && (
                <div className="github-alert github-alert-error">
                    <AlertTriangle size={18} aria-hidden="true" />
                    <span>{error}</span>
                </div>
            )}

            {status && !status.configured && (
                <div className="github-alert github-alert-warning">
                    <AlertTriangle size={18} aria-hidden="true" />
                    <span>
                        {t('github.configMissing', {
                            fields: status.missing_config.join(', '),
                        })}
                    </span>
                </div>
            )}

            {status?.connection_error && (
                <div className="github-alert github-alert-warning">
                    <AlertTriangle size={18} aria-hidden="true" />
                    <span>{status.connection_error}</span>
                </div>
            )}

            <div className="github-grid">
                <section className="github-panel github-panel-connection">
                    <div className="github-panel-head">
                        <div>
                            <h2>{t('github.connection.title')}</h2>
                            <p>{status?.app?.name || t('github.connection.appFallback')}</p>
                        </div>
                        <span className={cn('github-status-pill', installations.length > 0 && 'is-ready')}>
                            {installations.length > 0
                                ? t('github.connection.ready')
                                : t('github.connection.waiting')}
                        </span>
                    </div>

                    {installations.length > 0 ? (
                        <div className="github-installation-list">
                            {installations.map((installation: GitHubInstallation) => (
                                <button
                                    key={installation.installation_id}
                                    type="button"
                                    className={cn(
                                        'github-installation-item',
                                        selectedInstallationId === installation.installation_id && 'active'
                                    )}
                                    onClick={() => handleInstallationChange(installation.installation_id)}
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

                <section className="github-panel github-panel-repositories">
                    <div className="github-panel-head">
                        <div>
                            <h2>{t('github.repositories.title')}</h2>
                            <p>
                                {t('github.repositories.count', {
                                    count: repositories.length,
                                })}
                            </p>
                        </div>
                    </div>

                    <div className="github-search">
                        <Search size={17} aria-hidden="true" />
                        <input
                            value={repoSearch}
                            onChange={(event) => setRepoSearch(event.target.value)}
                            placeholder={t('github.repositories.searchPlaceholder')}
                            aria-label={t('github.repositories.searchAria')}
                        />
                    </div>

                    <div className="github-repo-list ui-scrollbar-thin">
                        {filteredRepositories.length === 0 ? (
                            <div className="github-empty-state">
                                {repositories.length === 0
                                    ? t('github.repositories.empty')
                                    : t('github.repositories.noResults')}
                            </div>
                        ) : (
                            filteredRepositories.map((repo) => (
                                <button
                                    key={repo.full_name}
                                    type="button"
                                    className={cn(
                                        'github-repo-item',
                                        selectedRepoName === repo.full_name && 'active'
                                    )}
                                    onClick={() => handleRepoSelect(repo)}
                                >
                                    <span>
                                        <strong>{repo.full_name}</strong>
                                        <small>
                                            {repo.private
                                                ? t('github.repositories.private')
                                                : t('github.repositories.public')}
                                            {' · '}
                                            {repo.default_branch}
                                        </small>
                                    </span>
                                    {repo.permissions.push && (
                                        <CheckCircle2 size={16} aria-label={t('github.repositories.writeAccess')} />
                                    )}
                                </button>
                            ))
                        )}
                    </div>
                </section>
            </div>

            <form className="github-agent-panel" onSubmit={handlePlan}>
                <div className="github-panel-head">
                    <div>
                        <h2>{t('github.agent.title')}</h2>
                        <p>{selectedRepoName || t('github.agent.noRepo')}</p>
                    </div>
                    <span className="github-status-pill">
                        {taskStatusLabel(t, activeTask?.status)}
                    </span>
                </div>

                <div className="github-agent-controls">
                    <label>
                        <span>{t('github.agent.branchLabel')}</span>
                        <input
                            value={baseBranch}
                            onChange={(event) => setBaseBranch(event.target.value)}
                            placeholder={selectedRepo?.default_branch || t('github.agent.branchPlaceholder')}
                        />
                    </label>
                    <label className="github-task-field">
                        <span>{t('github.agent.taskLabel')}</span>
                        <textarea
                            value={taskText}
                            onChange={(event) => setTaskText(event.target.value)}
                            placeholder={t('github.agent.taskPlaceholder')}
                            rows={5}
                            maxLength={4000}
                        />
                    </label>
                </div>

                <div className="github-agent-actions">
                    <button
                        type="submit"
                        className="github-primary-action"
                        disabled={!selectedInstallationId || !selectedRepoName || !baseBranch || !taskText.trim() || isPlanning}
                    >
                        {isPlanning ? <Loader2 size={17} className="animate-spin" /> : <GitBranch size={17} />}
                        {isPlanning ? t('github.agent.planning') : t('github.agent.createPlan')}
                    </button>
                </div>
            </form>

            {(visibleActivityItems.length > 0 || activeTask?.error) && (
                <section className="github-activity-panel">
                    <div className="github-panel-head">
                        <div>
                            <h2>{t('github.activity.title')}</h2>
                            <p>{t('github.activity.subtitle')}</p>
                        </div>
                    </div>

                    {activeTask?.error && (
                        <div className="github-alert github-alert-error github-task-error">
                            <AlertTriangle size={18} aria-hidden="true" />
                            <span>{localizedAgentMessage(t, activeTask.error)}</span>
                        </div>
                    )}

                    <div className="github-activity-list">
                        {visibleActivityItems.map((item, index) => {
                            const paths = activityPaths(item);
                            const preview = activityPreview(item);
                            const detail = activityDetail(t, item);
                            const status = item.status || 'done';
                            return (
                                <div
                                    key={`${item.code || 'activity'}-${item.created_at || index}`}
                                    className={cn('github-activity-item', `is-${status}`)}
                                >
                                    <span className="github-activity-icon" aria-hidden="true">
                                        {status === 'running' ? (
                                            <Loader2 size={15} className="animate-spin" />
                                        ) : status === 'error' ? (
                                            <AlertTriangle size={15} />
                                        ) : (
                                            <CheckCircle2 size={15} />
                                        )}
                                    </span>
                                    <div className="github-activity-body">
                                        <strong>{activityTitle(t, item)}</strong>
                                        {detail && <small>{detail}</small>}
                                        {paths.length > 0 && (
                                            <div className="github-activity-paths">
                                                {paths.slice(0, 8).map((path) => (
                                                    <code key={path}>{path}</code>
                                                ))}
                                                {paths.length > 8 && (
                                                    <code>
                                                        {t('github.activity.morePaths', {
                                                            count: paths.length - 8,
                                                        })}
                                                    </code>
                                                )}
                                            </div>
                                        )}
                                        {preview && (
                                            <pre className="github-activity-preview ui-scrollbar-thin">
                                                {preview}
                                            </pre>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </section>
            )}

            {activeTask?.plan && (
                <section className="github-plan-panel">
                    <div className="github-panel-head">
                        <div>
                            <h2>{t('github.plan.title')}</h2>
                            <p>
                                {localizedAgentMessage(t, activeTask.plan.summary)
                                    || t('github.plan.summaryFallback')}
                            </p>
                        </div>
                        <span className="github-status-pill">
                            {activeTask.plan.repo_map?.stats
                                ? t('github.plan.mapStats', {
                                    files: formatCount(activeTask.plan.repo_map.stats.files),
                                    directories: formatCount(activeTask.plan.repo_map.stats.directories),
                                })
                                : t('github.plan.mapReady')}
                        </span>
                    </div>

                    <div className="github-plan-grid">
                        <div className="github-plan-column">
                            <h3>{t('github.plan.steps')}</h3>
                            <ol>
                                {(activeTask.plan.steps || []).map((step, index) => (
                                    <li key={`${step.title}-${index}`}>
                                        <strong>{localizedAgentMessage(t, step.title)}</strong>
                                        {step.details && (
                                            <span>{localizedAgentMessage(t, step.details)}</span>
                                        )}
                                    </li>
                                ))}
                            </ol>
                        </div>
                        <div className="github-plan-column">
                            <h3>{t('github.plan.files')}</h3>
                            <div className="github-file-list">
                                {(activeTask.plan.files || []).map((file) => (
                                    <div key={`${file.action}-${file.path}`} className="github-file-row">
                                        <span>{file.path}</span>
                                        <small>{t(`github.plan.fileActions.${file.action}`)}</small>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    {activeTask.plan.risks && activeTask.plan.risks.length > 0 && (
                        <div className="github-risk-list">
                            {activeTask.plan.risks.map((risk) => (
                                <span key={risk}>{localizedAgentMessage(t, risk)}</span>
                            ))}
                        </div>
                    )}

                    <div className="github-agent-actions">
                        <button
                            type="button"
                            className="github-primary-action"
                            onClick={handleRun}
                            disabled={isRunning || activeTask.status !== 'planned'}
                        >
                            {isRunning ? <Loader2 size={17} className="animate-spin" /> : <GitPullRequest size={17} />}
                            {isRunning ? t('github.agent.running') : t('github.agent.confirmRun')}
                        </button>
                    </div>
                </section>
            )}

            {activeTask?.diff && (
                <section className="github-result-panel">
                    <div className="github-panel-head">
                        <div>
                            <h2>{t('github.result.title')}</h2>
                            <p>{activeTask.branch_name}</p>
                        </div>
                        {activeTask.pull_request_url && (
                            <a
                                className="github-secondary-action"
                                href={activeTask.pull_request_url}
                                target="_blank"
                                rel="noreferrer"
                            >
                                <ExternalLink size={16} />
                                {t('github.result.openPr')}
                            </a>
                        )}
                    </div>
                    <pre className="github-diff-view ui-scrollbar-thin">{activeTask.diff}</pre>
                </section>
            )}

            {activeTask?.status === 'completed_no_changes' && (
                <section className="github-result-panel">
                    <div className="github-panel-head">
                        <div>
                            <h2>{t('github.result.noChangesTitle')}</h2>
                            <p>
                                {activeTask.edits?.no_changes_reason
                                    || activeTask.edits?.summary
                                    || t('github.result.noChangesFallback')}
                            </p>
                        </div>
                    </div>
                    {activeTask.edits?.findings && activeTask.edits.findings.length > 0 && (
                        <div className="github-finding-list">
                            <h3>{t('github.result.findings')}</h3>
                            <ul>
                                {activeTask.edits.findings.map((finding) => (
                                    <li key={finding}>{finding}</li>
                                ))}
                            </ul>
                        </div>
                    )}
                    {activeTask.edits?.tests && activeTask.edits.tests.length > 0 && (
                        <div className="github-finding-list">
                            <h3>{t('github.result.tests')}</h3>
                            <ul>
                                {activeTask.edits.tests.map((test) => (
                                    <li key={test}>{test}</li>
                                ))}
                            </ul>
                        </div>
                    )}
                </section>
            )}
        </section>
    );
}
