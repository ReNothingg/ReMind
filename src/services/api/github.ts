import { fetchApi } from './transport';
import { GitHubAgentTask,GitHubAgentTaskResponse,GitHubRepositoriesResponse,GitHubRepository,GitHubStatus,GitHubStatusResponse } from './types/github';

export const githubApi = {
async getGitHubStatus(installationId?: number | null): Promise<GitHubStatus> {
        return fetchApi<GitHubStatusResponse>('/api/github/status', {
            method: 'GET',
            query: {
                installation_id: installationId || undefined,
            },
        });
    },

async disconnectGitHub(installationId?: number | null): Promise<{ deleted?: number }> {
        return fetchApi<{ deleted?: number }>('/api/github/disconnect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ installation_id: installationId || undefined }),
        });
    },

async listGitHubRepositories(installationId: number): Promise<GitHubRepository[]> {
        const data = await fetchApi<GitHubRepositoriesResponse>('/api/github/repositories', {
            method: 'GET',
            query: { installation_id: installationId },
        });
        return data.repositories || [];
    },

async createGitHubPlan(payload: {
        base_branch: string;
        installation_id: number;
        repo_full_name: string;
        task: string;
    }): Promise<GitHubAgentTask> {
        const data = await fetchApi<GitHubAgentTaskResponse>('/api/github/agent/plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!data.task) {
            throw new Error('GitHub task was not returned by the server.');
        }
        return data.task;
    },

async runGitHubTask(taskId: string): Promise<GitHubAgentTask> {
        const data = await fetchApi<GitHubAgentTaskResponse>('/api/github/agent/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_id: taskId }),
        });
        if (!data.task) {
            throw new Error('GitHub task was not returned by the server.');
        }
        return data.task;
    },

async getGitHubTask(taskId: string): Promise<GitHubAgentTask> {
        const data = await fetchApi<GitHubAgentTaskResponse>(
            `/api/github/tasks/${encodeURIComponent(taskId)}`,
            { method: 'GET' }
        );
        if (!data.task) {
            throw new Error('GitHub task was not returned by the server.');
        }
        return data.task;
    }
};
