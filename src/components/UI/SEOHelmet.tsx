import React, { useEffect } from 'react';


export const SEOHelmet = ({
    title = 'ReMind',
    description = 'ReMind для всех. Даже для тех, кто еще не понял, зачем.',
    keywords = 'ReMind, SynvexAI, AI, искусственный интеллект, чат-бот, LLM, GPT, Gemini, DeepSeek, продуктивность, нейросеть, ассистент',
    canonical = null,
    ogTitle = null,
    ogDescription = null,
    ogImage = 'https://chat.synvexai.com/images/banners/banner.png',
    ogType = 'website',
    twitterCard = 'summary_large_image',
    themeColor = null,
}) => {
    const fullTitle = title === 'ReMind' ? title : `${title} | ReMind`;
    const baseUrl = 'https://chat.synvexai.com';
    const fullCanonical = canonical ? `${baseUrl}${canonical}` : baseUrl;
    const finalOgTitle = ogTitle || fullTitle;
    const finalOgDescription = ogDescription || description;

    useEffect(() => {
        const createdNodes = [];

        const upsertMeta = ({ name, property, content }) => {
            if (!content) return;
            const selector = name
                ? `meta[name="${CSS.escape(name)}"]`
                : `meta[property="${CSS.escape(property)}"]`;
            let el = document.head.querySelector(selector);
            if (!el) {
                el = document.createElement('meta');
                if (name) el.setAttribute('name', name);
                if (property) el.setAttribute('property', property);
                el.setAttribute('data-remind-seo', '1');
                document.head.appendChild(el);
                createdNodes.push(el);
            }
            el.setAttribute('content', content);
        };

        const upsertLink = ({ rel, href }) => {
            if (!href) return;
            const selector = `link[rel="${CSS.escape(rel)}"]`;
            let el = document.head.querySelector(selector);
            if (!el) {
                el = document.createElement('link');
                el.setAttribute('rel', rel);
                el.setAttribute('data-remind-seo', '1');
                document.head.appendChild(el);
                createdNodes.push(el);
            }
            el.setAttribute('href', href);
        };

        document.title = fullTitle;

        upsertMeta({ name: 'description', content: description });
        upsertMeta({ name: 'keywords', content: keywords });

        upsertLink({ rel: 'canonical', href: fullCanonical });

        upsertMeta({ property: 'og:title', content: finalOgTitle });
        upsertMeta({ property: 'og:description', content: finalOgDescription });
        upsertMeta({ property: 'og:url', content: fullCanonical });
        upsertMeta({ property: 'og:type', content: ogType });
        upsertMeta({ property: 'og:site_name', content: 'ReMind' });
        upsertMeta({ property: 'og:locale', content: 'ru_RU' });

        if (ogImage) {
            upsertMeta({ property: 'og:image', content: ogImage });
            upsertMeta({ property: 'og:image:width', content: '1200' });
            upsertMeta({ property: 'og:image:height', content: '630' });
            upsertMeta({ property: 'og:image:alt', content: finalOgTitle });
        }

        upsertMeta({ name: 'twitter:card', content: twitterCard });
        upsertMeta({ name: 'twitter:title', content: finalOgTitle });
        upsertMeta({ name: 'twitter:description', content: finalOgDescription });
        if (ogImage) upsertMeta({ name: 'twitter:image', content: ogImage });

        if (themeColor) upsertMeta({ name: 'theme-color', content: themeColor });

        return () => {
            createdNodes.forEach((node) => node.parentNode?.removeChild(node));
        };
    }, [
        fullTitle,
        description,
        keywords,
        fullCanonical,
        finalOgTitle,
        finalOgDescription,
        ogImage,
        ogType,
        twitterCard,
        themeColor,
    ]);

    return null;
};

export default SEOHelmet;
