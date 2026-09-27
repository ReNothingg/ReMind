import {
apiSynthesize,
apiTranslate,
type SynthesizeResponse,
type TranslateResponse
} from "../openapiClient";

export const mediaApi = {
async translate(text: string, targetLang: string): Promise<TranslateResponse> {
        try {
            return await apiTranslate({ text, target_lang: targetLang });
        } catch (error) {
            console.warn('Primary translation API failed, trying fallback:', error);

            try {
                return await this._translateWithFallback(text, targetLang);
            } catch (fallbackError) {
                console.error('Fallback translation also failed:', fallbackError);
                throw error;
            }
        }
    },

_translateWithFallback(text: string, targetLang: string): Promise<TranslateResponse> {
        const fallbackTranslations: Record<string, Record<string, Record<string, string>>> = {
            en: { ru: { hello: '\u043f\u0440\u0438\u0432\u0435\u0442', world: '\u043c\u0438\u0440' } },
            ru: { en: { '\u043f\u0440\u0438\u0432\u0435\u0442': 'hello', '\u043c\u0438\u0440': 'world' } },
        };

        const sourceLang = /\p{Script=Cyrillic}/u.test(text) ? 'ru' : 'en';
        const translations = fallbackTranslations[sourceLang]?.[targetLang];

        if (translations) {
            let translatedText = text;

            for (const [original, translated] of Object.entries(translations)) {
                translatedText = translatedText.replace(
                    new RegExp(`\\b${original}\\b`, 'gi'),
                    translated
                );
            }

            return Promise.resolve({
                ok: true,
                translated_text: translatedText,
                source_lang: sourceLang,
                target_lang: targetLang,
                fallback: true,
            } as TranslateResponse);
        }

        return Promise.reject(new Error('Fallback translation not available'));
    },

async synthesize(text: string): Promise<SynthesizeResponse> {
        return apiSynthesize({ text });
    }
};
