import { fetchApi } from './transport';
import { AdminMind,AdminMindResponse,AdminMindsResponse,AdminMindUpdatePayload,AdminOverview,AdminPagination,AdminUser,AdminUserResponse,AdminUsersResponse,AdminUserUpdatePayload } from './types/admin';

export const adminApi = {
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
    }
};
