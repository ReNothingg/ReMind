import { fetchApi,toApiServiceError } from './transport';
import { LinkMetadataResponse } from './types/common';

export const resourcesApi = {
async getLinkMetadata(url: string): Promise<LinkMetadataResponse> {
        return fetchApi<LinkMetadataResponse>('/get-link-metadata', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
        });
    },

async fetchTextResource(filePath: string): Promise<string[]> {
        try {
            const response = await fetch(filePath, { cache: 'no-store' });
            if (!response.ok) {
                throw new Error(`Network response was not ok for ${filePath}`);
            }

            const textContent = await response.text();
            return textContent.split('\n').filter((phrase) => phrase.trim() !== '');
        } catch (error) {
            const typedError = toApiServiceError(error);
            console.warn(
                `Failed to load text resource ${filePath}:`,
                typedError.message
            );
            return [];
        }
    }
};
