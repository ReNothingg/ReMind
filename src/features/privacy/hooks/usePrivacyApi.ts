import { useCallback } from 'react';

interface DeletePrivacyOptions {
    deleteAccount: boolean;
}

async function privacyFetch(endpoint: string, options: RequestInit): Promise<unknown> {
    const response = await fetch(endpoint, {
        credentials: 'include',
        ...options,
    });
    if (!response.ok) {
        throw new Error(`Privacy API failed: HTTP ${response.status}`);
    }
    return response.json();
}

export function usePrivacyApi() {
    const exportUserData = useCallback(async () => {
        return privacyFetch('/api/privacy/export', { method: 'GET' });
    }, []);

    const deleteUserData = useCallback(async ({ deleteAccount }: DeletePrivacyOptions) => {
        return privacyFetch('/api/privacy/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delete_account: Boolean(deleteAccount) }),
        });
    }, []);

    return {
        exportUserData,
        deleteUserData,
    };
}
