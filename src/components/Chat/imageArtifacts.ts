const AUTO_CAPTURED_FIGURE_NAME = /^figure-\d+\.(?:png|jpe?g|webp)$/i;

const imageArtifactName = (image) => {
    if (image && typeof image === 'object' && image.original_name) {
        return String(image.original_name).split(/[\\/]/).pop() || '';
    }
    const path = typeof image === 'string' ? image : image?.url_path;
    if (!path) return '';
    return String(path).split(/[?#]/, 1)[0].split('/').pop() || '';
};

export const filterRedundantAutoCapturedImages = (images) => {
    if (!Array.isArray(images) || images.length < 2) return images || [];
    const hasExplicitPythonImage = images.some((image) => (
        image && typeof image === 'object'
        && image.source === 'python'
        && !AUTO_CAPTURED_FIGURE_NAME.test(imageArtifactName(image))
    ));
    if (!hasExplicitPythonImage) return images;
    return images.filter((image) => !(
        image && typeof image === 'object'
        && image.source === 'python'
        && AUTO_CAPTURED_FIGURE_NAME.test(imageArtifactName(image))
    ));
};

export const stripAttachedArtifactMarkdownImages = (text, images) => {
    const artifactNames = new Set(
        (Array.isArray(images) ? images : [])
            .map(imageArtifactName)
            .filter(Boolean)
            .map((name) => name.toLocaleLowerCase())
    );
    if (!artifactNames.size) return String(text || '');
    return String(text || '').replace(
        /!\[[^\]]*\]\(\s*<?([^\s)>]+)>?(?:\s+["'][^"']*["'])?\s*\)/gi,
        (markdown, target) => {
            const targetName = String(target).split(/[?#]/, 1)[0].split('/').pop();
            return targetName && artifactNames.has(targetName.toLocaleLowerCase()) ? '' : markdown;
        }
    );
};
