import { MindVisibility } from './minds';

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
        ai_feedback: {
            total: number;
            likes: number;
            dislikes: number;
            like_percent: number;
            dislike_percent: number;
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

export type AdminUsersResponse = {
    users?: AdminUser[];
    pagination?: AdminPagination;
};

export type AdminUserResponse = {
    user?: AdminUser;
};

export type AdminMindsResponse = {
    minds?: AdminMind[];
    pagination?: AdminPagination;
};

export type AdminMindResponse = {
    mind?: AdminMind;
};

export type AdminUserUpdatePayload = {
    is_banned?: boolean;
    is_blocked?: boolean;
    moderation_reason?: string | null;
    ban_reason?: string | null;
    block_reason?: string | null;
    banned_until?: string | null;
    blocked_until?: string | null;
    restriction_until?: string | null;
};

export type AdminMindUpdatePayload = {
    is_banned?: boolean;
    is_featured?: boolean;
    is_verified?: boolean;
    moderation_reason?: string | null;
};
