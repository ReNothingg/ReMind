import { fetchApi } from './transport';
import { ComposerToolOption,ModelListResponse,ModelOption } from './types/catalog';

export const catalogApi = {
async listModelCatalog(): Promise<{ models: ModelOption[]; tools: ComposerToolOption[] }> {
        const data = await fetchApi<ModelListResponse>('/api/models', { method: 'GET' });
        return { models: Array.isArray(data.models) ? data.models : [], tools: Array.isArray(data.tools) ? data.tools : [] };
    },

async listModels(): Promise<ModelOption[]> {
        const data = await fetchApi<ModelListResponse>('/api/models', { method: 'GET' });
        return Array.isArray(data.models) ? data.models : [];
    }
};
