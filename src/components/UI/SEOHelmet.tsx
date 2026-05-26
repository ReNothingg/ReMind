import { useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { getDocumentDirection, getOgLocale, getSiteCopy } from '../../content/siteCopy';

type MetaDescriptor = {
    name?: string;
    property?: string;
    content?: string | null;
};

type LinkDescriptor = {
    rel: string;
    href?: string | null;
};

function resolveAbsoluteUrl(value, baseUrl) {
    if (!value) return null;

    try {
        return new URL(value, baseUrl).toString();
    } catch {
        return null;
    }
}

const SEOHelmet = ({
    title = null,
    description = null,
    keywords = null,
    canonical = null,
    ogTitle = null,
    ogDescription = null,
    ogImage = null,
    ogType = 'website',
    twitterCard = 'summary_large_image',
    themeColor = '#111214',
}) => {
    const { i18n } = useTranslation();
    const currentPath = typeof window !== 'undefined' ? window.location.pathname : '/';
    const siteCopy = useMemo(() => getSiteCopy(i18n.resolvedLanguage), [i18n.resolvedLanguage]);
    const baseUrl =
        (typeof window !== 'undefined' && window.location.origin) ||
        import.meta.env.VITE_PUBLIC_BASE_URL ||
        'https://chat.synvexai.com';
    const pageTitle = title || (currentPath.startsWith('/c/') ? siteCopy.sharedChatTitle : 'ReMind');
    const fullTitle = pageTitle === 'ReMind' ? pageTitle : `${pageTitle} | ReMind`;
    const resolvedDescription =
        description || (currentPath.startsWith('/c/') ? siteCopy.sharedChatDescription : siteCopy.metaDescription);
    const resolvedKeywords = keywords || siteCopy.metaKeywords;
    const fullCanonical = resolveAbsoluteUrl(canonical || currentPath, baseUrl) || baseUrl;
    const finalOgTitle = ogTitle || fullTitle;
    const finalOgDescription = ogDescription || resolvedDescription;
    const finalOgImage =
        resolveAbsoluteUrl(ogImage || '/images/banners/main-banner.png', baseUrl) ||
        `${baseUrl}/images/banners/main-banner.png`;
    const currentLanguage = i18n.resolvedLanguage || i18n.language || 'en';
    const ogLocale = getOgLocale(currentLanguage);
    const documentDirection = getDocumentDirection(currentLanguage);

    useEffect(() => {
        const createdNodes = [];

        const upsertMeta = ({ name, property, content }: MetaDescriptor) => {
            if (!content) return;
            if (!name && !property) return;
            const selector = name
                ? `meta[name="${CSS.escape(name)}"]`
                : `meta[property="${CSS.escape(property as string)}"]`;
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

        const upsertLink = ({ rel, href }: LinkDescriptor) => {
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
        document.documentElement.lang = currentLanguage;
        document.documentElement.dir = documentDirection;

        upsertMeta({ name: 'description', content: resolvedDescription });
        upsertMeta({ name: 'keywords', content: resolvedKeywords });

        upsertLink({ rel: 'canonical', href: fullCanonical });

        upsertMeta({ property: 'og:title', content: finalOgTitle });
        upsertMeta({ property: 'og:description', content: finalOgDescription });
        upsertMeta({ property: 'og:url', content: fullCanonical });
        upsertMeta({ property: 'og:type', content: ogType });
        upsertMeta({ property: 'og:site_name', content: 'ReMind' });
        upsertMeta({ property: 'og:locale', content: ogLocale });

        if (finalOgImage) {
            upsertMeta({ property: 'og:image', content: finalOgImage });
            upsertMeta({ property: 'og:image:width', content: '1200' });
            upsertMeta({ property: 'og:image:height', content: '630' });
            upsertMeta({ property: 'og:image:alt', content: finalOgTitle });
        }

        upsertMeta({ name: 'twitter:card', content: twitterCard });
        upsertMeta({ name: 'twitter:title', content: finalOgTitle });
        upsertMeta({ name: 'twitter:description', content: finalOgDescription });
        if (finalOgImage) upsertMeta({ name: 'twitter:image', content: finalOgImage });

        if (themeColor) upsertMeta({ name: 'theme-color', content: themeColor });

        return () => {
            createdNodes.forEach((node) => node.parentNode?.removeChild(node));
        };
    }, [
        currentLanguage,
        documentDirection,
        fullTitle,
        resolvedDescription,
        resolvedKeywords,
        fullCanonical,
        finalOgTitle,
        finalOgDescription,
        finalOgImage,
        ogType,
        ogLocale,
        twitterCard,
        themeColor,
    ]);

    return null;
};

export default SEOHelmet;
