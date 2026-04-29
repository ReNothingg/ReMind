import { API_BASE_URL } from '../utils/constants';

const CSRF_COOKIE_KEY = 'csrf_token';
const CSRF_HEADER_KEY = 'X-CSRF-Token';
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);
const CSRF_ERROR_CODES = new Set(['csrf_failed', 'csrf_validation_failed']);

let csrfTokenCache = '';

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
    if (csrfTokenCache) {
        return csrfTokenCache;
    }
    const cookieToken = getCookie(CSRF_COOKIE_KEY);
    if (cookieToken) {
        csrfTokenCache = cookieToken;
    }
    return cookieToken;
}

export function withCsrfHeaders(options: RequestInit = {}): RequestInit & { headers: Headers } {
    const method = (options.method || 'GET').toUpperCase();
    const headers = new Headers(options.headers || {});

    if (!SAFE_METHODS.has(method)) {
        const token = getCsrfToken();
        if (token) {
            headers.set(CSRF_HEADER_KEY, token);
        }
    }

    return { ...options, method, headers };
}

function rememberCsrfTokenFromResponse(response: Response): void {
    const token = response.headers.get(CSRF_HEADER_KEY);
    if (token) {
        csrfTokenCache = token;
    }
}

async function refreshCsrfToken(): Promise<string> {
    try {
        const response = await fetch(buildApiUrl('/health', { format: 'json' }), {
            method: 'GET',
            credentials: 'include',
            headers: { Accept: 'application/json' },
        });
        rememberCsrfTokenFromResponse(response);
    } catch {
        // The original unsafe request will surface the actionable API error.
    }
    return getCsrfToken();
}

async function ensureCsrfToken(method: string): Promise<void> {
    if (SAFE_METHODS.has(method) || getCsrfToken()) {
        return;
    }
    await refreshCsrfToken();
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

function isCsrfValidationError(status: number, data: unknown, message: string): boolean {
    if (status !== 403) {
        return false;
    }

    if (data && typeof data === 'object') {
        const apiError = (data as { error?: unknown }).error;
        if (apiError && typeof apiError === 'object') {
            const code = (apiError as { code?: unknown }).code;
            if (typeof code === 'string' && CSRF_ERROR_CODES.has(code)) {
                return true;
            }
            const nestedMessage = (apiError as { message?: unknown }).message;
            if (typeof nestedMessage === 'string' && nestedMessage.toLowerCase().includes('csrf')) {
                return true;
            }
        }
        if (typeof apiError === 'string' && apiError.toLowerCase().includes('csrf')) {
            return true;
        }
    }

    return message.toLowerCase().includes('csrf');
}

function buildApiClientError(response: Response, data: unknown): ApiClientError {
    const err = new ApiClientError(
        (data as { error?: string | { message?: string } } | null)?.error &&
        typeof (data as { error?: unknown }).error === 'object'
            ? ((data as { error?: { message?: string } }).error?.message ||
                `HTTP error: ${response.status}`)
            : ((data as { error?: string } | null)?.error || `HTTP error: ${response.status}`)
    );
    err.status = response.status;
    err.data = data;
    return err;
}

export async function requestJson<TResponse>(
    path: string,
    options: RequestJsonOptions = {}
): Promise<TResponse> {
    const method = (options.method || 'GET').toUpperCase();
    await ensureCsrfToken(method);
    const requestOptions = withCsrfHeaders({
        ...options,
        credentials: options.credentials || 'include',
    });
    const url = buildApiUrl(path, options.query);
    let response = await fetch(url, requestOptions);
    rememberCsrfTokenFromResponse(response);

    if (!response.ok) {
        let data = await readResponseData(response);
        let err = buildApiClientError(response, data);

        if (!SAFE_METHODS.has(method) && isCsrfValidationError(response.status, data, err.message)) {
            csrfTokenCache = '';
            await refreshCsrfToken();
            response = await fetch(url, withCsrfHeaders(requestOptions));
            rememberCsrfTokenFromResponse(response);
            if (response.ok) {
                if (response.status === 204) {
                    return null as TResponse;
                }
                return response.json() as Promise<TResponse>;
            }
            data = await readResponseData(response);
            err = buildApiClientError(response, data);
        }

        throw err;
    }

    if (response.status === 204) {
        return null as TResponse;
    }

    return response.json() as Promise<TResponse>;
}
