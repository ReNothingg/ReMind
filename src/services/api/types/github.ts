
export type GitHubInstallation = {
    id: number;
    installation_id: number;
    account_login: string;
    account_html_url?: string | null;
    account_avatar_url?: string | null;
    target_type?: string | null;
    repository_selection?: string | null;
    permissions?: Record<string, unknown>;
};

export type GitHubRepository = {
    default_branch: string;
    full_name: string;
    html_url: string;
    permissions: {
        admin: boolean;
        pull: boolean;
        push: boolean;
    };
    private: boolean;
};

export type GitHubPlanFile = {
    action: 'inspect' | 'edit' | 'create' | 'delete';
    path: string;
    reason?: string;
};

export type GitHubPlanStep = {
    details?: string;
    title: string;
};

export type GitHubAgentActivity = {
    code?: string;
    created_at?: string;
    meta?: Record<string, unknown>;
    status?: 'done' | 'error' | 'running' | 'warning' | string;
};

export type GitHubAgentPlan = {
    activity?: GitHubAgentActivity[];
    base_commit_sha?: string;
    branch_suffix?: string;
    commit_message?: string;
    files?: GitHubPlanFile[];
    pr_body?: string;
    pr_title?: string;
    repo_map?: {
        source?: string;
        stats?: {
            directories?: number;
            files?: number;
            max_depth?: number;
            nodes?: number;
        };
        truncated?: boolean;
    };
    risks?: string[];
    steps?: GitHubPlanStep[];
    summary?: string;
};

export type GitHubAgentTask = {
    base_branch: string;
    branch_name?: string | null;
    created_at?: string | null;
    diff?: string | null;
    edits?: {
        activity?: GitHubAgentActivity[];
        edits?: Array<Record<string, unknown>>;
        findings?: string[];
        no_changes_reason?: string;
        summary?: string;
        tests?: string[];
    };
    error?: string | null;
    id: string;
    installation_id: number;
    plan?: GitHubAgentPlan;
    pull_request_number?: number | null;
    pull_request_url?: string | null;
    repo_full_name: string;
    status: string;
    task: string;
    updated_at?: string | null;
};

export type GitHubStatus = {
    app?: {
        install_url?: string;
        name?: string;
        page_url?: string;
        slug?: string;
    };
    configured: boolean;
    connection_error?: string | null;
    installations: GitHubInstallation[];
    missing_config: string[];
    repositories: GitHubRepository[];
    selected_installation_id?: number | null;
    urls?: {
        app_page?: string;
        callback?: string;
        connect?: string;
        disconnect?: string;
        install?: string;
        install_page?: string;
        setup?: string;
    };
};

export type GitHubStatusResponse = GitHubStatus;

export type GitHubRepositoriesResponse = {
    repositories?: GitHubRepository[];
};

export type GitHubAgentTaskResponse = {
    task?: GitHubAgentTask;
};
