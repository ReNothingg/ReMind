import { API_BASE_URL } from '../utils/constants';

const CSRF_COOKIE_KEY = 'csrf_token';
const CSRF_HEADER_KEY = 'X-CSRF-Token';
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

export class ApiClientError extends Error {
    status?: number;
    data?: unknown;
}

export type RequestJsonOptions = RequestInit & {
    query?: Record<string, unknown>;
};

function buildQueryString(query?: Record<string, unknown>): string {
    if (!query) return '';

    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
        if (value === undefined || value === null || value === '') return;
        params.set(key, String(value));
    });

    const serialized = params.toString();
    return serialized ? `?${serialized}` : '';
}

export function buildApiUrl(path: string, query?: Record<string, unknown>): string {
    const baseURL = API_BASE_URL || '';
    return `${baseURL}${path}${buildQueryString(query)}`;
}

function getCookie(name: string): string {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
        return parts.pop()?.split(';').shift() || '';
    }
    return '';
}

export function getCsrfToken(): string {
    return getCookie(CSRF_COOKIE_KEY);
}

export function withCsrfHeaders(options: RequestInit = {}): RequestInit & { headers: Headers } {
    const method = (options.method || 'GET').toUpperCase();
    const headers = new Headers(options.headers || {});

    if (!SAFE_METHODS.has(method) && !headers.has(CSRF_HEADER_KEY)) {
        const token = getCsrfToken();
        if (token) {
            headers.set(CSRF_HEADER_KEY, token);
        }
    }

    return { ...options, method, headers };
}

async function readResponseData(response: Response): Promise<unknown> {
    try {
        return await response.json();
    } catch {
        try {
            return await response.text();
        } catch {
            return null;
        }
    }
}

export function extractApiErrorMessage(error: unknown, fallback: string): string {
    if (error instanceof ApiClientError) {
        const apiError = error.data as
            | { error?: string | { message?: string } }
            | undefined;

        if (typeof apiError?.error === 'string' && apiError.error) {
            return apiError.error;
        }
        if (
            apiError?.error &&
            typeof apiError.error === 'object' &&
            typeof apiError.error.message === 'string' &&
            apiError.error.message
        ) {
            return apiError.error.message;
        }
        return error.message || fallback;
    }

    if (error instanceof Error) {
        return error.message || fallback;
    }

    return fallback;
}

export async function requestJson<TResponse>(
    path: string,
    options: RequestJsonOptions = {}
): Promise<TResponse> {
    const requestOptions = withCsrfHeaders({
        ...options,
        credentials: options.credentials || 'include',
    });
    const url = buildApiUrl(path, options.query);
    const response = await fetch(url, requestOptions);

    if (!response.ok) {
        const data = await readResponseData(response);
        const err = new ApiClientError(
            (data as { error?: string | { message?: string } } | null)?.error &&
            typeof (data as { error?: unknown }).error === 'object'
                ? ((data as { error?: { message?: string } }).error?.message ||
                    `HTTP error: ${response.status}`)
                : ((data as { error?: string } | null)?.error || `HTTP error: ${response.status}`)
        );
        err.status = response.status;
        err.data = data;
        throw err;
    }

    if (response.status === 204) {
        return null as TResponse;
    }

    return response.json() as Promise<TResponse>;
}
