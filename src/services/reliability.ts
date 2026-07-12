import { ApiClientError, requestJson } from './http';

export type QueuedChatMessage = {
    id: string;
    createdAt: number;
    sessionId: string;
    text: string;
    model: string;
    options: Record<string, unknown>;
    files: File[];
    apiHistory?: unknown[];
    ownerKey: string;
};

export type SyncedDraft = {
    content: string;
    session_id: string | null;
    device_id: string;
    revision: number;
    updated_at: number;
};

const DB_NAME = 'remind-reliability';
const DB_VERSION = 1;
const QUEUE_STORE = 'chatQueue';
const DEVICE_KEY = 'remind_device_id';
const MAX_QUEUED_MESSAGES = 50;
const MAX_QUEUED_FILE_BYTES = 200 * 1024 * 1024;

function openDatabase(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, DB_VERSION);
        request.onupgradeneeded = () => {
            const db = request.result;
            if (!db.objectStoreNames.contains(QUEUE_STORE)) {
                db.createObjectStore(QUEUE_STORE, { keyPath: 'id' });
            }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

async function withStore<T>(
    mode: IDBTransactionMode,
    action: (store: IDBObjectStore) => IDBRequest<T>
): Promise<T> {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
        const transaction = db.transaction(QUEUE_STORE, mode);
        const request = action(transaction.objectStore(QUEUE_STORE));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
        transaction.oncomplete = () => db.close();
        transaction.onerror = () => reject(transaction.error);
    });
}

export function getDeviceId(): string {
    let value = localStorage.getItem(DEVICE_KEY);
    if (!value) {
        value = crypto.randomUUID();
        localStorage.setItem(DEVICE_KEY, value);
    }
    return value;
}

export async function enqueueChatMessage(item: QueuedChatMessage): Promise<void> {
    const db = await openDatabase();
    await new Promise<void>((resolve, reject) => {
        const transaction = db.transaction(QUEUE_STORE, 'readwrite');
        const store = transaction.objectStore(QUEUE_STORE);
        const readRequest = store.getAll();
        let validationError: Error | null = null;

        readRequest.onsuccess = () => {
            const existing = ((readRequest.result || []) as QueuedChatMessage[])
                .filter((queued) => queued.id !== item.id);
            const existingBytes = existing.reduce(
                (total, queued) => total + (queued.files || []).reduce(
                    (sum, file) => sum + Number(file?.size || 0),
                    0
                ),
                0
            );
            const incomingBytes = (item.files || []).reduce(
                (sum, file) => sum + Number(file?.size || 0),
                0
            );
            if (
                existing.length >= MAX_QUEUED_MESSAGES ||
                existingBytes + incomingBytes > MAX_QUEUED_FILE_BYTES
            ) {
                validationError = new Error('offline_queue_full');
                transaction.abort();
                return;
            }
            store.put(item);
        };
        readRequest.onerror = () => transaction.abort();
        transaction.oncomplete = () => resolve();
        transaction.onabort = () => reject(validationError || transaction.error || new Error('offline_queue_failed'));
        transaction.onerror = () => reject(transaction.error || new Error('offline_queue_failed'));
    }).finally(() => db.close());
}

export async function listQueuedChatMessages(ownerKey?: string): Promise<QueuedChatMessage[]> {
    const items = await withStore<QueuedChatMessage[]>('readonly', (store) => store.getAll());
    return items
        .filter((item) => !ownerKey || item.ownerKey === ownerKey)
        .sort((a, b) => a.createdAt - b.createdAt);
}

export async function removeQueuedChatMessage(id: string): Promise<void> {
    await withStore('readwrite', (store) => store.delete(id));
}

export async function reconcileQueuedChatOwner(ownerKey: string): Promise<void> {
    const db = await openDatabase();
    await new Promise<void>((resolve, reject) => {
        const transaction = db.transaction(QUEUE_STORE, 'readwrite');
        const store = transaction.objectStore(QUEUE_STORE);
        const request = store.getAll();
        request.onsuccess = () => {
            const items = (request.result || []) as QueuedChatMessage[];
            for (const item of items) {
                if (item.ownerKey === ownerKey) continue;
                if (ownerKey.startsWith('user:') && item.ownerKey === 'guest') {
                    store.put({ ...item, ownerKey });
                } else if (ownerKey.startsWith('user:')) {
                    store.delete(item.id);
                }
            }
        };
        request.onerror = () => transaction.abort();
        transaction.oncomplete = () => resolve();
        transaction.onabort = () => reject(transaction.error || new Error('offline_queue_reconcile_failed'));
        transaction.onerror = () => reject(transaction.error || new Error('offline_queue_reconcile_failed'));
    }).finally(() => db.close());
}

export async function clearLocalReliabilityData(): Promise<void> {
    try {
        const db = await openDatabase();
        await new Promise<void>((resolve, reject) => {
            const transaction = db.transaction(QUEUE_STORE, 'readwrite');
            transaction.objectStore(QUEUE_STORE).clear();
            transaction.oncomplete = () => resolve();
            transaction.onerror = () => reject(transaction.error);
        });
        db.close();
    } catch {
    }
    Object.keys(localStorage)
        .filter((key) => key.startsWith('remind_chat_draft_v2:'))
        .forEach((key) => localStorage.removeItem(key));
}

export async function getRemoteDraft(): Promise<SyncedDraft | null> {
    const data = await requestJson<{ draft?: SyncedDraft | null }>('/api/user/draft');
    return data.draft || null;
}

export async function saveRemoteDraft(
    content: string,
    sessionId: string | null,
    baseRevision: number | null
): Promise<SyncedDraft> {
    try {
        const data = await requestJson<{ draft?: SyncedDraft }>('/api/user/draft', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                content,
                session_id: sessionId,
                device_id: getDeviceId(),
                base_revision: baseRevision,
            }),
        });
        if (!data.draft) throw new Error('draft_save_invalid_response');
        return data.draft;
    } catch (error) {
        if (error instanceof ApiClientError && error.status === 409) {
            const conflict = error.data as { draft?: SyncedDraft } | undefined;
            if (conflict?.draft) return conflict.draft;
        }
        throw error;
    }
}

export async function deleteRemoteDraft(): Promise<void> {
    await requestJson('/api/user/draft', {
        method: 'DELETE',
    });
}
