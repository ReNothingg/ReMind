import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { Gauge } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { readContextUsage } from '../../features/chat/contextUsage';

export default function ContextUsagePopover({ value, children, className = '', hoverTarget, suppressed = false, onOpen }: {
    value: unknown;
    children?: ReactNode;
    className?: string;
    hoverTarget?: RefObject<HTMLElement | null>;
    suppressed?: boolean;
    onOpen?: () => void;
}) {
    const { t, i18n } = useTranslation();
    const usage = readContextUsage(value);
    const [open, setOpen] = useState(false);
    const [position, setPosition] = useState({ top: 12, left: 12, width: 320 });
    const anchor = useRef<HTMLButtonElement>(null);
    const popup = useRef<HTMLDivElement>(null);
    const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const id = useId();
    const visible = Boolean(usage) && open && !suppressed;
    const cancelClose = useCallback(() => { if (closeTimer.current) clearTimeout(closeTimer.current); closeTimer.current = null; }, []);
    const scheduleClose = useCallback(() => { cancelClose(); closeTimer.current = setTimeout(() => setOpen(false), 180); }, [cancelClose]);
    useEffect(() => () => { if (closeTimer.current) clearTimeout(closeTimer.current); }, []);
    useEffect(() => {
        const target = hoverTarget?.current;
        if (!target || !usage) return;
        const enter = (event: PointerEvent) => {
            if (event.pointerType !== 'touch' && !suppressed) { cancelClose(); setOpen(true); }
        };
        target.addEventListener('pointerenter', enter);
        target.addEventListener('pointerleave', scheduleClose);
        return () => {
            target.removeEventListener('pointerenter', enter);
            target.removeEventListener('pointerleave', scheduleClose);
        };
    }, [hoverTarget, suppressed, usage, cancelClose, scheduleClose]);
    useLayoutEffect(() => {
        if (!visible) return;
        const update = () => {
            const rect = anchor.current?.getBoundingClientRect();
            if (!rect) return;
            const width = Math.min(350, window.innerWidth - 24);
            const height = popup.current?.offsetHeight || 230;
            const top = rect.top >= height + 12 ? rect.top - height - 8 : Math.min(rect.bottom + 8, Math.max(12, window.innerHeight - height - 12));
            setPosition({ top: Math.max(12, top), left: Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12)), width });
        };
        update();
        const observer = new ResizeObserver(update);
        if (popup.current) observer.observe(popup.current);
        const dismiss = (event: PointerEvent) => { if (!anchor.current?.contains(event.target as Node) && !popup.current?.contains(event.target as Node)) setOpen(false); };
        const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); anchor.current?.focus(); } };
        window.addEventListener('resize', update);
        window.addEventListener('scroll', update, true);
        document.addEventListener('pointerdown', dismiss);
        document.addEventListener('keydown', escape);
        return () => {
            observer.disconnect();
            window.removeEventListener('resize', update);
            window.removeEventListener('scroll', update, true);
            document.removeEventListener('pointerdown', dismiss);
            document.removeEventListener('keydown', escape);
        };
    }, [visible]);
    const compact = new Intl.NumberFormat(i18n.language, { notation: 'compact', maximumFractionDigits: 1 });
    const percent = usage ? new Intl.NumberFormat(i18n.language, { style: 'percent', maximumFractionDigits: 1 }).format(usage.input_tokens / usage.context_limit) : '';
    const entries = usage ? [
        { key: 'system', tokens: usage.system_tokens },
        { key: 'tools', tokens: usage.tool_tokens },
        { key: 'messages', tokens: usage.message_tokens },
    ] : [];
    return <>
        <button ref={anchor} type="button" className={`context-usage-trigger ${className}`} aria-label={t('contextUsage.label')} aria-expanded={visible} aria-describedby={visible ? id : undefined} disabled={!usage}
            onPointerEnter={event => { if (usage && event.pointerType !== 'touch' && !suppressed) { cancelClose(); setOpen(true); } }} onPointerLeave={scheduleClose}
            onBlur={scheduleClose}
            onClick={() => { if (!usage) return; cancelClose(); onOpen?.(); setOpen(true); }}>
            {children || <><Gauge aria-hidden="true" />{usage && <span>{percent}</span>}</>}
        </button>
        {visible && usage && createPortal(<div ref={popup} id={id} role="tooltip" className="context-usage-popover" style={position} onPointerEnter={cancelClose} onPointerLeave={scheduleClose}>
            <>
                <div className="context-usage-heading"><span>{t('contextUsage.used', { percent })}</span><span>{usage.estimated_total ? '≈' : ''}{compact.format(usage.input_tokens)} / {compact.format(usage.context_limit)}</span></div>
                <div className="context-usage-bar" aria-hidden="true">{entries.map(entry => <span key={entry.key} data-category={entry.key} style={{ width: `${Math.min(100, entry.tokens / usage.context_limit * 100)}%` }} />)}</div>
                <dl>{entries.map(entry => <div key={entry.key}><dt><span className="context-usage-dot" data-category={entry.key} />{t(`contextUsage.${entry.key}`)}</dt><dd>≈{compact.format(entry.tokens)}</dd></div>)}</dl>
                <p>{t('contextUsage.estimate')}</p>
            </>
        </div>, document.body)}
    </>;
}
