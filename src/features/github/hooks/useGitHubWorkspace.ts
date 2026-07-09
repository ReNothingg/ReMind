import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    apiService,
    type GitHubAgentTask,
    type GitHubInstallation,
    type GitHubRepository,
    type GitHubStatus,
} from '../../../services/api';
import { localizedAgentMessage, type Translate } from '../githubPresentation';

export type GitHubLoadState = 'idle' | 'loading' | 'error';

const EMPTY_INSTALLATIONS: GitHubInstallation[] = [];
const EMPTY_REPOSITORIES: GitHubRepository[] = [];

type UseGitHubWorkspaceOptions = {
    isAuthenticated: boolean;
    t: Translate;
};

function hasInstallation(
    installations: GitHubInstallation[],
    installationId: number | null
): installationId is number {
    return installationId !== null
        && installations.some((installation) => installation.installation_id === installationId);
}

function selectedInstallationFrom(
    connection: GitHubStatus,
    currentInstallationId: number | null
): number | null {
    const installations = connection.installations || EMPTY_INSTALLATIONS;
    if (hasInstallation(installations, currentInstallationId)) {
        return currentInstallationId;
    }
    return connection.selected_installation_id || installations[0]?.installation_id || null;
}

export function useGitHubWorkspace({ isAuthenticated, t }: UseGitHubWorkspaceOptions) {
    const [status, setStatus] = useState<GitHubStatus | null>(null);
    const [loadState, setLoadState] = useState<GitHubLoadState>('idle');
    const [repositoryLoadState, setRepositoryLoadState] = useState<GitHubLoadState>('idle');
    const [error, setError] = useState('');
    const [selectedInstallationId, setSelectedInstallationId] = useState<number | null>(null);
    const [repositories, setRepositories] = useState<GitHubRepository[]>(EMPTY_REPOSITORIES);
    const [selectedRepoName, setSelectedRepoName] = useState('');
    const [baseBranch, setBaseBranch] = useState('');
    const [taskText, setTaskText] = useState('');
    const [activeTask, setActiveTask] = useState<GitHubAgentTask | null>(null);
    const [isPlanning, setIsPlanning] = useState(false);
    const [isRunning, setIsRunning] = useState(false);

    const connectionRequestId = useRef(0);
    const repositoryRequestId = useRef(0);
    const selectedInstallationIdRef = useRef<number | null>(null);
    const selectedRepoNameRef = useRef('');

    useEffect(() => {
        selectedInstallationIdRef.current = selectedInstallationId;
    }, [selectedInstallationId]);

    useEffect(() => {
        selectedRepoNameRef.current = selectedRepoName;
    }, [selectedRepoName]);

    const installations = status?.installations || EMPTY_INSTALLATIONS;
    const selectedRepo = useMemo(
        () => repositories.find((repository) => repository.full_name === selectedRepoName) || null,
        [repositories, selectedRepoName]
    );

    const resetWorkspace = useCallback(() => {
        connectionRequestId.current += 1;
        repositoryRequestId.current += 1;
        selectedInstallationIdRef.current = null;
        selectedRepoNameRef.current = '';
        setStatus(null);
        setRepositories(EMPTY_REPOSITORIES);
        setSelectedInstallationId(null);
        setSelectedRepoName('');
        setBaseBranch('');
        setTaskText('');
        setActiveTask(null);
        setError('');
        setLoadState('idle');
        setRepositoryLoadState('idle');
    }, []);

    const loadConnection = useCallback(async (): Promise<GitHubStatus | null> => {
        if (!isAuthenticated) {
            resetWorkspace();
            return null;
        }

        const requestId = ++connectionRequestId.current;
        setLoadState('loading');
        setError('');

        try {
            // This endpoint is DB-only. Network calls to GitHub are deliberately
            // reserved for an explicit repository load below.
            const data = await apiService._fetch<GitHubStatus>('/api/github/connection', {
                method: 'GET',
            });
            if (requestId !== connectionRequestId.current) {
                return null;
            }

            const connection: GitHubStatus = {
                ...data,
                installations: data.installations || EMPTY_INSTALLATIONS,
                missing_config: data.missing_config || [],
                repositories: [],
            };
            const nextInstallationId = selectedInstallationFrom(
                connection,
                selectedInstallationIdRef.current
            );

            setStatus(connection);
            selectedInstallationIdRef.current = nextInstallationId;
            setSelectedInstallationId(nextInstallationId);
            setLoadState('idle');
            return connection;
        } catch (loadError) {
            if (requestId !== connectionRequestId.current) {
                return null;
            }
            setError(loadError instanceof Error ? loadError.message : t('github.errors.loadStatus'));
            setLoadState('error');
            return null;
        }
    }, [isAuthenticated, resetWorkspace, t]);

    const loadRepositories = useCallback(async (installationId: number): Promise<GitHubRepository[]> => {
        const requestId = ++repositoryRequestId.current;
        setRepositoryLoadState('loading');
        setError('');

        try {
            const nextRepositories = await apiService.listGitHubRepositories(installationId);
            if (requestId !== repositoryRequestId.current) {
                return EMPTY_REPOSITORIES;
            }

            const currentRepoName = selectedRepoNameRef.current;
            const selectedRepository = nextRepositories.find(
                (repository) => repository.full_name === currentRepoName
            ) || nextRepositories[0] || null;

            setRepositories(nextRepositories);
            selectedRepoNameRef.current = selectedRepository?.full_name || '';
            setSelectedRepoName(selectedRepository?.full_name || '');
            setBaseBranch((currentBranch) => {
                const currentRepository = nextRepositories.find(
                    (repository) => repository.full_name === currentRepoName
                );
                return currentRepository
                    ? (currentBranch || currentRepository.default_branch)
                    : (selectedRepository?.default_branch || '');
            });
            setRepositoryLoadState('idle');
            return nextRepositories;
        } catch (loadError) {
            if (requestId !== repositoryRequestId.current) {
                return EMPTY_REPOSITORIES;
            }
            setRepositories(EMPTY_REPOSITORIES);
            setSelectedRepoName('');
            selectedRepoNameRef.current = '';
            setBaseBranch('');
            setError(loadError instanceof Error ? loadError.message : t('github.errors.loadStatus'));
            setRepositoryLoadState('error');
            return EMPTY_REPOSITORIES;
        }
    }, [t]);

    useEffect(() => {
        if (!isAuthenticated) {
            resetWorkspace();
            return;
        }
        void loadConnection();
    }, [isAuthenticated, loadConnection, resetWorkspace]);

    useEffect(() => {
        if (!isAuthenticated || !selectedInstallationId) {
            repositoryRequestId.current += 1;
            setRepositories(EMPTY_REPOSITORIES);
            setRepositoryLoadState('idle');
            return;
        }
        void loadRepositories(selectedInstallationId);
    }, [isAuthenticated, loadRepositories, selectedInstallationId]);

    const selectInstallation = useCallback((installationId: number) => {
        if (installationId === selectedInstallationIdRef.current) {
            return;
        }
        repositoryRequestId.current += 1;
        selectedInstallationIdRef.current = installationId;
        selectedRepoNameRef.current = '';
        setSelectedInstallationId(installationId);
        setRepositories(EMPTY_REPOSITORIES);
        setSelectedRepoName('');
        setBaseBranch('');
        setActiveTask(null);
    }, []);

    const selectRepository = useCallback((repository: GitHubRepository) => {
        selectedRepoNameRef.current = repository.full_name;
        setSelectedRepoName(repository.full_name);
        setBaseBranch(repository.default_branch);
        setActiveTask(null);
    }, []);

    const refresh = useCallback(async () => {
        const connection = await loadConnection();
        if (!connection) {
            return;
        }

        const currentInstallationId = selectedInstallationIdRef.current;
        const nextInstallationId = selectedInstallationFrom(connection, currentInstallationId);
        if (nextInstallationId && nextInstallationId === currentInstallationId) {
            await loadRepositories(nextInstallationId);
        }
    }, [loadConnection, loadRepositories]);

    const createPlan = useCallback(async () => {
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
    }, [baseBranch, selectedInstallationId, selectedRepoName, t, taskText]);

    const runPlan = useCallback(async () => {
        if (!activeTask?.id) {
            return;
        }

        const taskId = activeTask.id;
        setIsRunning(true);
        setError('');
        try {
            const result = await apiService.runGitHubTask(taskId);
            setActiveTask(result);
            void refresh();
        } catch (runError) {
            setError(runError instanceof Error
                ? localizedAgentMessage(t, runError.message)
                : t('github.errors.run'));
            try {
                setActiveTask(await apiService.getGitHubTask(taskId));
            } catch {
                // Keep the actionable operation error visible.
            }
        } finally {
            setIsRunning(false);
        }
    }, [activeTask?.id, refresh, t]);

    return {
        activeTask,
        baseBranch,
        createPlan,
        error,
        installations,
        isPlanning,
        isRunning,
        loadState,
        repositories,
        repositoryLoadState,
        refresh,
        runPlan,
        selectedInstallationId,
        selectedRepo,
        selectedRepoName,
        selectInstallation,
        selectRepository,
        setBaseBranch,
        setTaskText,
        status,
        taskText,
    };
}
