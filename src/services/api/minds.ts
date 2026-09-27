import { fetchApi } from './transport';
import { Mind,MindCategory,MindCategoryResponse,MindDeleteResponse,MindListResponse,MindPayload,MindResponse } from './types/minds';

export const mindsApi = {
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
    }
};
