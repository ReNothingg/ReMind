import { fetchApi } from './transport';
import { PrivacyDeleteResponse } from './types/common';

export const privacyApi = {
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
    }
};
