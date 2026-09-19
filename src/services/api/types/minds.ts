
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

export type MindListResponse = {
    minds?: Mind[];
    categories?: MindCategory[];
};

export type MindResponse = {
    mind?: Mind;
};

export type MindCategoryResponse = {
    categories?: MindCategory[];
};

export type MindDeleteResponse = Record<string, unknown> | null;
