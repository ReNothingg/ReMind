import { fetchApi,getGuestSessionToken } from './transport';
import { CanvasActionResponse,CanvasPythonExecutionResponse,CanvasSaveResponse,CanvasTextdoc } from './types/chat';

export const canvasApi = {
async saveCanvasTextdoc(sessionId: string, textdoc: CanvasTextdoc): Promise<CanvasTextdoc> {
        const token = getGuestSessionToken(sessionId);
        const headers: HeadersInit = {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
        };
        const response = await fetchApi<CanvasSaveResponse>(
            `/sessions/${encodeURIComponent(sessionId)}/canvas`,
            {
                method: 'PUT',
                headers,
                body: JSON.stringify({ textdoc }),
            }
        );
        return response.textdoc;
    },

async executeCanvasPython(code: string): Promise<CanvasPythonExecutionResponse> {
        return fetchApi<CanvasPythonExecutionResponse>('/api/python/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code }),
        });
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
    }
};
