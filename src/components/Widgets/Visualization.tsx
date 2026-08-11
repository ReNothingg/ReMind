import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import katex from 'katex';
import { useSettings } from '../../context/SettingsContext';
import {
    buildVisualizationDocument,
    MAX_VISUALIZATION_SOURCE_BYTES,
    readVisualizationContext,
} from './visualizationRuntime';

type VisualizationState = {
    html?: string;
    title?: string;
    mode?: 'normal' | 'wide';
    error?: 'too_large';
};

type VisualizationProps = {
    initialState: VisualizationState;
    onFollowUp?: (prompt: string) => void;
};

type PendingFollowUp = {
    prompt: string;
    title: string;
};

const MIN_FRAME_HEIGHT = 120;
const MAX_FRAME_HEIGHT = 1800;

const Visualization = ({ initialState, onFollowUp }: VisualizationProps) => {
    const { t } = useTranslation();
    const { settings } = useSettings();
    const iframeRef = useRef<HTMLIFrameElement | null>(null);
    const channelId = `visualization-${useId()}`;
    const [height, setHeight] = useState(280);
    const [hostReady, setHostReady] = useState(false);
    const [pendingFollowUp, setPendingFollowUp] = useState<PendingFollowUp | null>(null);
    const html = typeof initialState?.html === 'string' ? initialState.html : '';
    const sourceBytes = new TextEncoder().encode(html).byteLength;
    const isTooLarge = initialState?.error === 'too_large' || sourceBytes > MAX_VISUALIZATION_SOURCE_BYTES;
    const title = String(initialState?.title || '').trim().slice(0, 120) || t('visualizations.defaultTitle');
    const mode = initialState?.mode === 'wide' ? 'wide' : 'normal';

    const documentSource = useMemo(() => {
        if (!html || isTooLarge) return '';
        return buildVisualizationDocument({
            fragment: html,
            context: readVisualizationContext(settings || {}),
            channelId,
        });
    }, [channelId, html, isTooLarge, settings]);

    useEffect(() => {
        const handleMessage = (event: MessageEvent) => {
            if (event.source !== iframeRef.current?.contentWindow) return;
            if (event.data?.channelId !== channelId) return;

            if (event.data?.type === 'remind:visualization:resize') {
                const nextHeight = Number(event.data.height);
                if (Number.isFinite(nextHeight)) {
                    setHeight(Math.min(MAX_FRAME_HEIGHT, Math.max(MIN_FRAME_HEIGHT, Math.ceil(nextHeight))));
                }
                return;
            }

            if (event.data?.type === 'remind:visualization:follow-up' && onFollowUp) {
                const prompt = String(event.data.prompt || '').trim().slice(0, 4000);
                const requestTitle = String(event.data.title || '').trim().slice(0, 250);
                if (prompt) setPendingFollowUp({ prompt, title: requestTitle });
                return;
            }

            if (event.data?.type === 'remind:visualization:math-request') {
                const requestId = String(event.data.requestId || '').slice(0, 100);
                const expression = String(event.data.expression || '').slice(0, 4000);
                if (!requestId || !expression) return;
                const rendered = katex.renderToString(expression, {
                    displayMode: event.data.displayMode === true,
                    throwOnError: false,
                    strict: false,
                    trust: false,
                });
                iframeRef.current?.contentWindow?.postMessage({
                    type: 'remind:visualization:math-result',
                    channelId,
                    requestId,
                    html: rendered,
                }, '*');
            }
        };

        window.addEventListener('message', handleMessage);
        return () => window.removeEventListener('message', handleMessage);
    }, [channelId, onFollowUp]);

    useEffect(() => {
        if (!hostReady || !documentSource) return;
        iframeRef.current?.contentWindow?.postMessage({
            type: 'remind:visualization:render',
            channelId,
            documentSource,
            title,
        }, '*');
    }, [channelId, documentSource, hostReady, title]);

    if (isTooLarge) {
        return <div className="visualization-error" role="alert">{t('visualizations.tooLarge')}</div>;
    }

    if (!documentSource) {
        return <div className="visualization-error" role="alert">{t('visualizations.invalid')}</div>;
    }

    return (
        <section className={`visualization-instance${mode === 'wide' ? ' is-wide' : ''}`} aria-label={title}>
            <iframe
                ref={iframeRef}
                className="visualization-frame"
                sandbox="allow-scripts"
                src="/visualization-host.html"
                style={{ height }}
                title={title}
                loading="lazy"
                onLoad={() => setHostReady(true)}
            />
            {pendingFollowUp && (
                <div className="visualization-follow-up" role="dialog" aria-label={t('visualizations.followUpTitle')}>
                    <div className="visualization-follow-up-copy">
                        <strong>{pendingFollowUp.title || t('visualizations.followUpTitle')}</strong>
                        <span>{pendingFollowUp.prompt}</span>
                    </div>
                    <div className="visualization-follow-up-actions">
                        <button
                            type="button"
                            className="ui-action-button"
                            onClick={() => setPendingFollowUp(null)}
                        >
                            {t('visualizations.cancel')}
                        </button>
                        <button
                            type="button"
                            className="ui-action-button is-primary"
                            onClick={() => {
                                onFollowUp?.(pendingFollowUp.prompt);
                                setPendingFollowUp(null);
                            }}
                        >
                            {t('visualizations.followUpSend')}
                        </button>
                    </div>
                </div>
            )}
        </section>
    );
};

export default Visualization;
