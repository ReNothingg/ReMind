import { SERIOUS_ERROR_KEYPHRASES } from '../utils/constants';
import {
    apiGetSessionHistory,
    apiListSessions,
    apiSynthesize,
    apiTranslate,
    type ListSessionsResponse,
    type SessionHistoryResponse,
    type SynthesizeResponse,
    type TranslateResponse,
} from './openapiClient';
import {
    buildApiUrl,
    getCsrfToken,
    requestJson,
    withCsrfHeaders,
    type RequestJsonOptions,
} from './http';

const GUEST_SESSION_TOKENS_KEY = 'guest_chat_tokens';

type GuestSessionTokenMap = Record<string, string>;

type ApiServiceError = Error & {
    data?: unknown;
    isSerious?: boolean;
    status?: number;
};

type ChatWidgetUpdate = Record<string, unknown>;

export type ChatStreamResult = {
    aborted?: boolean;
    end_of_stream?: boolean;
    images?: string[] | string;
    reply?: string;
    reply_part?: string;
    sessionId?: string;
    sessionSlug?: string;
    sources?: unknown[];
    status?: string;
    thinkingTime?: number;
    widget_update?: ChatWidgetUpdate;
    [key: string]: unknown;
};

type ChatCallbacks = {
    onError?: (error: Error) => void;
    onComplete?: (data: ChatStreamResult) => void;
    onPart?: (data: ChatStreamResult) => void;
    onWidgetUpdate?: (widgetData: ChatWidgetUpdate) => void;
};

type ListSessionsOptions =
    | string
    | {
          idsQuery?: string;
          page?: number;
          pageSize?: number;
      };

type SessionShareResponse = {
    is_owner?: boolean;
    is_public?: boolean;
    public_id?: string | null;
    read_only?: boolean;
    session_id?: string;
    share_url?: string | null;
    [key: string]: unknown;
};

type SessionRenameResponse = {
    title?: string;
    [key: string]: unknown;
};

export type MindVisibility = 'private' | 'link' | 'store';

export type MindCategory = {
    id: string;
    label: string;
};

export type Mind = {
    id: number;
    public_id: string;
    name: string;
    description: string;
    instructions?: string;
    starters: string[];
    category: string;
    visibility: MindVisibility;
    is_verified: boolean;
    is_system: boolean;
    is_featured?: boolean;
    is_banned?: boolean;
    moderation_reason?: string | null;
    is_owner: boolean;
    can_edit: boolean;
    is_pinned: boolean;
    created_at?: string | null;
    updated_at?: string | null;
};

export type MindPayload = {
    name: string;
    description: string;
    instructions: string;
    starters: string[];
    category: string;
    visibility: MindVisibility;
};

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

type MindListResponse = {
    minds?: Mind[];
    categories?: MindCategory[];
};

type MindResponse = {
    mind?: Mind;
};

export type SessionHistoryWithMind = SessionHistoryResponse & {
    mind?: Mind | null;
};

type SessionMindResponse = {
    mind?: Mind | null;
    session_id?: string;
};

type MindCategoryResponse = {
    categories?: MindCategory[];
};

export type AdminPagination = {
    page: number;
    page_size: number;
    total: number;
};

export type AdminUser = {
    id: number;
    username: string;
    name?: string | null;
    email: string;
    is_confirmed: boolean;
    is_admin: boolean;
    is_super_admin: boolean;
    is_banned: boolean;
    is_blocked: boolean;
    moderation_reason?: string | null;
    ban_reason?: string | null;
    block_reason?: string | null;
    banned_until?: string | null;
    blocked_until?: string | null;
    oauth_provider?: string | null;
    created_at?: string | null;
    mind_count: number;
    chat_count: number;
};

export type AdminMind = {
    id: number;
    public_id: string;
    name: string;
    description: string;
    category: string;
    visibility: MindVisibility;
    is_verified: boolean;
    is_featured: boolean;
    is_banned: boolean;
    is_system: boolean;
    moderation_reason?: string | null;
    owner?: {
        id: number;
        username: string;
        email: string;
    } | null;
    created_at?: string | null;
    updated_at?: string | null;
};

export type AdminOverview = {
    admin: {
        id: number;
        username: string;
        is_super_admin: boolean;
    };
    stats: {
        users: {
            total: number;
            confirmed: number;
            admins: number;
            banned: number;
            blocked: number;
            new_24h: number;
        };
        minds: {
            total: number;
            store: number;
            featured: number;
            banned: number;
            verified: number;
            new_24h: number;
        };
        sessions: {
            total: number;
            updated_24h: number;
        };
    };
    server: {
        status: string;
        uptime_seconds: number;
        started_at?: string | null;
        timestamp: string;
        process: {
            pid: number;
            python: string;
            platform: string;
            memory: {
                max_rss_bytes?: number | null;
            };
            python_executable?: string;
            implementation?: string;
            machine?: string;
            processor?: string;
            cpu_count?: number | null;
            thread_count?: number | null;
            cwd?: string;
            debug?: boolean;
            env?: string;
            load_average?: number[] | null;
        };
        components: {
            database: { status: string; engine?: string };
            redis: { status: string };
            storage: Array<{
                key: string;
                path: string;
                exists: boolean;
                writable: boolean;
                disk?: {
                    total_bytes: number;
                    used_bytes: number;
                    free_bytes: number;
                } | null;
            }>;
        };
    };
    operations: {
        health: {
            score: number;
            level: string;
            issues: string[];
        };
        alerts: Array<{
            tone: string;
            title: string;
            detail: string;
            action: string;
        }>;
        queues: {
            unconfirmed_users: number;
            restricted_users: number;
            store_minds: number;
            unverified_store_minds: number;
            banned_minds: number;
        };
        growth_7d: {
            users: number;
            minds: number;
            sessions: number;
        };
        top_users: Array<{
            id: number;
            username: string;
            email: string;
            chat_count: number;
            mind_count: number;
            is_restricted: boolean;
            created_at?: string | null;
        }>;
        recent_audit: Array<{
            timestamp?: string | null;
            event_type: string;
            severity: string;
            endpoint?: string | null;
            method?: string | null;
            client_type?: string | null;
            user_hash?: string | null;
            details?: Record<string, unknown>;
        }>;
    };
};

type AdminUsersResponse = {
    users?: AdminUser[];
    pagination?: AdminPagination;
};

type AdminUserResponse = {
    user?: AdminUser;
};

type AdminMindsResponse = {
    minds?: AdminMind[];
    pagination?: AdminPagination;
};

type AdminMindResponse = {
    mind?: AdminMind;
};

type AdminUserUpdatePayload = {
    is_banned?: boolean;
    is_blocked?: boolean;
    moderation_reason?: string | null;
    ban_reason?: string | null;
    block_reason?: string | null;
    banned_until?: string | null;
    blocked_until?: string | null;
    restriction_until?: string | null;
};

type AdminMindUpdatePayload = {
    is_banned?: boolean;
    is_featured?: boolean;
    is_verified?: boolean;
    moderation_reason?: string | null;
};

type CanvasActionResponse = Record<string, unknown>;
type LinkMetadataResponse = Record<string, unknown>;
type PrivacyDeleteResponse = Record<string, unknown>;
type SessionDeleteResponse = Record<string, unknown>;
type MindDeleteResponse = Record<string, unknown> | null;
type GitHubStatusResponse = GitHubStatus;
type GitHubRepositoriesResponse = {
    repositories?: GitHubRepository[];
};
type GitHubAgentTaskResponse = {
    task?: GitHubAgentTask;
};

export { getCsrfToken };

function getGuestSessionToken(sessionId: string): string {
    if (!sessionId) return '';

    try {
        const raw = localStorage.getItem(GUEST_SESSION_TOKENS_KEY);
        const tokens = raw ? (JSON.parse(raw) as GuestSessionTokenMap) : {};
        return tokens[sessionId] || '';
    } catch {
        return '';
    }
}

function getGuestSessionTokens(): GuestSessionTokenMap {
    try {
        const raw = localStorage.getItem(GUEST_SESSION_TOKENS_KEY);
        const tokens = raw ? (JSON.parse(raw) as unknown) : {};
        return tokens && typeof tokens === 'object' ? (tokens as GuestSessionTokenMap) : {};
    } catch {
        return {};
    }
}

function toApiServiceError(error: unknown): ApiServiceError {
    return error instanceof Error ? (error as ApiServiceError) : new Error(String(error));
}

function isGenericHttpMessage(message: string): boolean {
    return /^HTTP error: \d+$/.test(message.trim());
}

async function fetchApi<TResponse = unknown>(
    endpoint: string,
    options: RequestJsonOptions = {}
): Promise<TResponse> {
    try {
        return await requestJson<TResponse>(endpoint, options);
    } catch (error) {
        const typedError = toApiServiceError(error);
        if (typeof typedError.data === 'string' && typedError.data.trim()) {
            typedError.message = typedError.data;
            typedError.data = { error: typedError.data };
        } else if (isGenericHttpMessage(typedError.message)) {
            const structuredData =
                typedError.data && typeof typedError.data === 'object'
                    ? (typedError.data as { error?: string })
                    : undefined;
            if (structuredData?.error) {
                typedError.message = structuredData.error;
            }
        }
        const normalizedMessage = typedError.message.toLowerCase();

        if (SERIOUS_ERROR_KEYPHRASES.some((phrase) => normalizedMessage.includes(phrase))) {
            typedError.isSerious = true;
        }

        if (
            !(
                normalizedMessage.includes('failed to fetch') ||
                typedError.name === 'AbortError'
            )
        ) {
            const errorDetails = typedError.data ? JSON.stringify(typedError.data) : '';
            console.error(
                `API Error (${endpoint}):`,
                typedError.message,
                errorDetails || typedError
            );
        }

        throw typedError;
    }
}

export const apiService = {
    baseURL: buildApiUrl(''),

    _fetch: fetchApi,

    async chat(
        formData: FormData,
        signal?: AbortSignal,
        callbacks: ChatCallbacks = {}
    ): Promise<void> {
        const { onPart, onComplete, onError, onWidgetUpdate } = callbacks;

        try {
            const response = await fetch(
                buildApiUrl('/chat'),
                withCsrfHeaders({
                    method: 'POST',
                    body: formData,
                    credentials: 'include',
                    ...(signal ? { signal } : {}),
                })
            );

            if (!response.ok) {
                const fallbackMessage = `HTTP error! status: ${response.status}`;
                const errorData = (await response
                    .json()
                    .catch(() => ({ error: fallbackMessage }))) as { error?: string };
                throw new Error(errorData.error || fallbackMessage);
            }

            const contentType = response.headers.get('content-type');
            if (contentType?.includes('text/event-stream')) {
                const reader = response.body?.getReader();
                if (!reader) {
                    throw new Error('Streaming response body is missing.');
                }

                const decoder = new TextDecoder();
                let buffer = '';
                let finalData: ChatStreamResult = {};

                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const parts = buffer.split('\n\n');
                    buffer = parts.pop() ?? '';

                    for (const part of parts) {
                        if (!part.startsWith('data: ')) {
                            continue;
                        }

                        try {
                            const data = JSON.parse(part.substring(6)) as ChatStreamResult;

                            if (data.widget_update && onWidgetUpdate) {
                                try {
                                    onWidgetUpdate(data.widget_update);
                                } catch (widgetError) {
                                    console.warn('onWidgetUpdate handler error', widgetError);
                                }

                                finalData = { ...finalData, widget_update: data.widget_update };
                                continue;
                            }

                            const shouldEmitPart = [
                                'reply_part',
                                'status',
                                'images',
                                'sources',
                                'thinkingTime',
                            ].some((key) => key in data);

                            if (shouldEmitPart) {
                                onPart?.(data);
                            }

                            if ('reply' in data || data.end_of_stream) {
                                finalData = { ...finalData, ...data };
                            }

                            if ('sources' in data) finalData.sources = data.sources;
                            if ('images' in data) finalData.images = data.images;
                            if ('thinkingTime' in data) {
                                finalData.thinkingTime = data.thinkingTime;
                            }
                            if ('status' in data) finalData.status = data.status;
                            if ('sessionId' in data) finalData.sessionId = data.sessionId;
                            if ('sessionSlug' in data) {
                                finalData.sessionSlug = data.sessionSlug;
                            }

                            const knownKeys = new Set([
                                'reply',
                                'reply_part',
                                'end_of_stream',
                                'images',
                                'sources',
                                'thinkingTime',
                                'status',
                                'aborted',
                                'sessionId',
                                'sessionSlug',
                                'widget_update',
                            ]);

                            Object.keys(data).forEach((key) => {
                                if (!knownKeys.has(key)) {
                                    finalData[key] = data[key];
                                }
                            });
                        } catch (chunkError) {
                            console.error(
                                'Error parsing stream data chunk:',
                                chunkError,
                                'Chunk:',
                                part.substring(6)
                            );
                        }
                    }
                }

                onComplete?.(finalData);
                return;
            }

            const data = (await response.json()) as ChatStreamResult;
            onComplete?.(data);
        } catch (error) {
            const typedError = toApiServiceError(error);

            if (typedError.name !== 'AbortError') {
                console.error('API Chat Error:', typedError);
                onError?.(typedError);
            } else {
                onComplete?.({ aborted: true });
            }
        }
    },

    async listSessions(
        options: ListSessionsOptions = ''
    ): Promise<ListSessionsResponse> {
        const guestTokens = getGuestSessionTokens();
        const headers: HeadersInit | undefined = Object.keys(guestTokens).length
            ? { 'X-Guest-Tokens': JSON.stringify(guestTokens) }
            : undefined;

        let idsQuery = '';
        let page = 1;
        let pageSize = 50;

        if (typeof options === 'string') {
            idsQuery = options;
        } else if (options && typeof options === 'object') {
            idsQuery = options.idsQuery || '';
            page = Number(options.page || 1);
            pageSize = Number(options.pageSize || 50);
        }

        if (typeof options === 'string') {
            return apiListSessions(idsQuery ? { ids: idsQuery } : {}, headers);
        }

        const query: { ids?: string; page: number; page_size: number } = {
            page,
            page_size: pageSize,
        };
        if (idsQuery) query.ids = idsQuery;

        return apiListSessions(query, headers);
    },

    async getSessionHistory(sessionId: string): Promise<SessionHistoryWithMind> {
        const token = getGuestSessionToken(sessionId);
        const headers: HeadersInit | undefined = token
            ? { Authorization: `Bearer ${token}` }
            : undefined;
        return apiGetSessionHistory(sessionId, headers) as Promise<SessionHistoryWithMind>;
    },

    async toggleShare(
        sessionId: string,
        isPublic = true
    ): Promise<SessionShareResponse> {
        return fetchApi<SessionShareResponse>(
            `/sessions/${encodeURIComponent(sessionId)}/share`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_public: Boolean(isPublic) }),
            }
        );
    },

    async deleteSession(sessionId: string): Promise<SessionDeleteResponse> {
        const token = getGuestSessionToken(sessionId);
        const headers: HeadersInit | undefined = token
            ? { Authorization: `Bearer ${token}` }
            : undefined;
        return fetchApi<SessionDeleteResponse>(`/sessions/${encodeURIComponent(sessionId)}`, {
            method: 'DELETE',
            ...(headers ? { headers } : {}),
        });
    },

    async renameSession(
        sessionId: string,
        newTitle: string
    ): Promise<SessionRenameResponse> {
        return fetchApi<SessionRenameResponse>(
            `/sessions/${encodeURIComponent(sessionId)}/rename`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: newTitle }),
            }
        );
    },

    async setSessionMind(sessionId: string, mindId: string | null): Promise<Mind | null> {
        const data = await fetchApi<SessionMindResponse>(
            `/sessions/${encodeURIComponent(sessionId)}/mind`,
            {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mind_id: mindId }),
            }
        );
        return data.mind || null;
    },

    async listMindCategories(): Promise<MindCategory[]> {
        const data = await fetchApi<MindCategoryResponse>('/api/minds/categories', {
            method: 'GET',
        });
        return data.categories || [];
    },

    async listMinds(params: {
        category?: string;
        limit?: number;
        mine?: boolean;
        q?: string;
    } = {}): Promise<MindListResponse> {
        return fetchApi<MindListResponse>('/api/minds', {
            method: 'GET',
            query: {
                category: params.category,
                limit: params.limit,
                mine: params.mine ? '1' : undefined,
                q: params.q,
            },
        });
    },

    async getMind(publicId: string): Promise<Mind | null> {
        const data = await fetchApi<MindResponse>(
            `/api/minds/${encodeURIComponent(publicId)}`,
            { method: 'GET' }
        );
        return data.mind || null;
    },

    async createMind(payload: MindPayload): Promise<Mind> {
        const data = await fetchApi<MindResponse>('/api/minds', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!data.mind) {
            throw new Error('Mind was not returned by the server.');
        }
        return data.mind;
    },

    async updateMind(publicId: string, payload: MindPayload): Promise<Mind> {
        const data = await fetchApi<MindResponse>(
            `/api/minds/${encodeURIComponent(publicId)}`,
            {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }
        );
        if (!data.mind) {
            throw new Error('Mind was not returned by the server.');
        }
        return data.mind;
    },

    async deleteMind(publicId: string): Promise<MindDeleteResponse> {
        return fetchApi<MindDeleteResponse>(`/api/minds/${encodeURIComponent(publicId)}`, {
            method: 'DELETE',
        });
    },

    async listPinnedMinds(): Promise<Mind[]> {
        const data = await fetchApi<MindListResponse>('/api/minds/pinned', {
            method: 'GET',
        });
        return data.minds || [];
    },

    async setMindPinned(publicId: string, pinned: boolean): Promise<Mind | null> {
        const data = await fetchApi<MindResponse>(
            `/api/minds/${encodeURIComponent(publicId)}/pin`,
            {
                method: pinned ? 'POST' : 'DELETE',
            }
        );
        return data.mind || null;
    },

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
    },

    async getAdminOverview(): Promise<AdminOverview> {
        return fetchApi<AdminOverview>('/api/admin/overview', { method: 'GET' });
    },

    async listAdminUsers(params: {
        page?: number;
        pageSize?: number;
        q?: string;
        status?: string;
    } = {}): Promise<{ users: AdminUser[]; pagination: AdminPagination }> {
        const data = await fetchApi<AdminUsersResponse>('/api/admin/users', {
            method: 'GET',
            query: {
                page: params.page,
                page_size: params.pageSize,
                q: params.q,
                status: params.status,
            },
        });
        return {
            users: data.users || [],
            pagination: data.pagination || { page: 1, page_size: 25, total: 0 },
        };
    },

    async updateAdminUser(userId: number, payload: AdminUserUpdatePayload): Promise<AdminUser> {
        const data = await fetchApi<AdminUserResponse>(`/api/admin/users/${userId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!data.user) {
            throw new Error('User was not returned by the server.');
        }
        return data.user;
    },

    async setAdminRole(userId: number, isAdmin: boolean): Promise<AdminUser> {
        const data = await fetchApi<AdminUserResponse>(`/api/admin/users/${userId}/admin`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_admin: isAdmin }),
        });
        if (!data.user) {
            throw new Error('User was not returned by the server.');
        }
        return data.user;
    },

    async listAdminMinds(params: {
        page?: number;
        pageSize?: number;
        q?: string;
        status?: string;
    } = {}): Promise<{ minds: AdminMind[]; pagination: AdminPagination }> {
        const data = await fetchApi<AdminMindsResponse>('/api/admin/minds', {
            method: 'GET',
            query: {
                page: params.page,
                page_size: params.pageSize,
                q: params.q,
                status: params.status,
            },
        });
        return {
            minds: data.minds || [],
            pagination: data.pagination || { page: 1, page_size: 25, total: 0 },
        };
    },

    async updateAdminMind(publicId: string, payload: AdminMindUpdatePayload): Promise<AdminMind> {
        const data = await fetchApi<AdminMindResponse>(
            `/api/admin/minds/${encodeURIComponent(publicId)}`,
            {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }
        );
        if (!data.mind) {
            throw new Error('Mind was not returned by the server.');
        }
        return data.mind;
    },

    async canvasAction(
        actionData: Record<string, unknown>,
        signal?: AbortSignal
    ): Promise<CanvasActionResponse> {
        return fetchApi<CanvasActionResponse>('/canvas-action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(actionData),
            ...(signal ? { signal } : {}),
        });
    },

    async translate(text: string, targetLang: string): Promise<TranslateResponse> {
        try {
            return await apiTranslate({ text, target_lang: targetLang });
        } catch (error) {
            console.warn('Primary translation API failed, trying fallback:', error);

            try {
                return await this._translateWithFallback(text, targetLang);
            } catch (fallbackError) {
                console.error('Fallback translation also failed:', fallbackError);
                throw error;
            }
        }
    },

    _translateWithFallback(text: string, targetLang: string): Promise<TranslateResponse> {
        const fallbackTranslations: Record<string, Record<string, Record<string, string>>> = {
            en: { ru: { hello: '\u043f\u0440\u0438\u0432\u0435\u0442', world: '\u043c\u0438\u0440' } },
            ru: { en: { '\u043f\u0440\u0438\u0432\u0435\u0442': 'hello', '\u043c\u0438\u0440': 'world' } },
        };

        const sourceLang = /\p{Script=Cyrillic}/u.test(text) ? 'ru' : 'en';
        const translations = fallbackTranslations[sourceLang]?.[targetLang];

        if (translations) {
            let translatedText = text;

            for (const [original, translated] of Object.entries(translations)) {
                translatedText = translatedText.replace(
                    new RegExp(`\\b${original}\\b`, 'gi'),
                    translated
                );
            }

            return Promise.resolve({
                ok: true,
                translated_text: translatedText,
                source_lang: sourceLang,
                target_lang: targetLang,
                fallback: true,
            } as TranslateResponse);
        }

        return Promise.reject(new Error('Fallback translation not available'));
    },

    async synthesize(text: string): Promise<SynthesizeResponse> {
        return apiSynthesize({ text });
    },

    async getLinkMetadata(url: string): Promise<LinkMetadataResponse> {
        return fetchApi<LinkMetadataResponse>('/get-link-metadata', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });
    },

    async exportPrivacyData(): Promise<unknown> {
        return fetchApi('/api/privacy/export', { method: 'GET' });
    },

    async deletePrivacyData(
        deleteAccount = false
    ): Promise<PrivacyDeleteResponse> {
        return fetchApi<PrivacyDeleteResponse>('/api/privacy/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delete_account: Boolean(deleteAccount) }),
        });
    },

    async fetchTextResource(filePath: string): Promise<string[]> {
        try {
            const response = await fetch(filePath, { cache: 'no-store' });
            if (!response.ok) {
                throw new Error(`Network response was not ok for ${filePath}`);
            }

            const textContent = await response.text();
            return textContent.split('\n').filter((phrase) => phrase.trim() !== '');
        } catch (error) {
            const typedError = toApiServiceError(error);
            console.warn(
                `Failed to load text resource ${filePath}:`,
                typedError.message
            );
            return [];
        }
    },
};
