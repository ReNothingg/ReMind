import { type FormEvent, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Circle, LoaderCircle } from 'lucide-react';

type Step = { id: string; title: string; status: 'pending' | 'in_progress' | 'completed' };
type Question = { id: string; question: string; options: string[] };
type Panel = { title: string; steps?: Step[]; questions?: Question[] };

function validText(value: unknown, maximum: number): value is string {
    return typeof value === 'string' && value.trim().length > 0 && value.length <= maximum;
}

function readPanel(value: unknown, kind: 'plan' | 'questions'): Panel | null {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const state = value as Record<string, unknown>;
    if (!validText(state.title, 200)) return null;
    const rows = state[kind === 'plan' ? 'steps' : 'questions'];
    if (!Array.isArray(rows) || rows.length < 1 || rows.length > (kind === 'plan' ? 12 : 3)) return null;
    const ids = new Set<string>();
    for (const row of rows) {
        if (!row || typeof row !== 'object' || !validText(row.id, 40) || ids.has(row.id)) return null;
        ids.add(row.id);
        if (kind === 'plan') {
            if (!validText(row.title, 240) || !['pending', 'in_progress', 'completed'].includes(row.status)) return null;
        } else if (!validText(row.question, 500) || !Array.isArray(row.options) || row.options.length < 2 || row.options.length > 4 || !row.options.every(option => validText(option, 160))) {
            return null;
        }
    }
    return kind === 'plan' ? { title: state.title, steps: rows as Step[] } : { title: state.title, questions: rows as Question[] };
}

export default function ToolPanel({ kind, state, onReply, disabled = false }: {
    kind: 'plan' | 'questions';
    state: unknown;
    onReply?: (message: string) => unknown;
    disabled?: boolean;
}) {
    const { t } = useTranslation();
    const formId = useId();
    const [answers, setAnswers] = useState<Record<string, string>>({});
    const [custom, setCustom] = useState<Record<string, string>>({});
    const [submitted, setSubmitted] = useState(false);
    const [failed, setFailed] = useState(false);
    const panel = readPanel(state, kind);
    if (!panel) return null;
    const locked = disabled || !onReply || submitted;
    const ready = panel.questions?.every(question => (custom[question.id] || answers[question.id] || '').trim());
    const submit = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!ready || locked || !onReply || !panel.questions) return;
        setSubmitted(true);
        setFailed(false);
        const reply = [t('toolPanels.answerMessage', { title: panel.title }), ...panel.questions.map(question => `${question.question}\n${(custom[question.id] || answers[question.id] || '').trim()}`)].join('\n\n');
        try {
            await onReply(reply);
        } catch {
            setFailed(true);
            setSubmitted(false);
        }
    };
    return (
        <section className={`chat-tool-panel chat-tool-panel-${kind}`} aria-label={t(`toolPanels.${kind}`)}>
            <h3>{panel.title}</h3>
            {panel.steps && <ol className="chat-tool-plan">
                {panel.steps.map(step => <li key={step.id} data-status={step.status}>
                    <span className="chat-tool-step-icon" title={t(`toolPanels.status.${step.status}`)}>
                        {step.status === 'completed' ? <Check aria-hidden="true" /> : step.status === 'in_progress' ? <LoaderCircle aria-hidden="true" /> : <Circle aria-hidden="true" />}
                        <span className="think-sr-only">{t(`toolPanels.status.${step.status}`)}</span>
                    </span>
                    <span className="chat-tool-step-title">{step.title}</span>
                </li>)}
            </ol>}
            {panel.questions && <form onSubmit={submit}>
                {panel.questions.map((question, index) => <fieldset key={question.id} disabled={locked}>
                    <legend>{question.question}</legend>
                    <div className="chat-tool-choices">
                        {question.options.map(option => <label key={option}>
                            <input type="radio" name={`${formId}-${index}`} checked={answers[question.id] === option && !custom[question.id]} onChange={() => {
                                setAnswers(current => ({ ...current, [question.id]: option }));
                                setCustom(current => ({ ...current, [question.id]: '' }));
                            }} />
                            <span>{option}</span>
                        </label>)}
                    </div>
                    <label htmlFor={`${formId}-custom-${index}`}>{t('toolPanels.customAnswer')}</label>
                    <textarea id={`${formId}-custom-${index}`} rows={2} maxLength={2000} value={custom[question.id] || ''} onChange={event => setCustom(current => ({ ...current, [question.id]: event.target.value }))} />
                </fieldset>)}
                <button type="submit" disabled={locked || !ready}>{t(submitted ? 'toolPanels.sent' : 'toolPanels.send')}</button>
                {!onReply && <p>{t('toolPanels.readOnly')}</p>}
                {failed && <p role="alert">{t('toolPanels.sendFailed')}</p>}
            </form>}
        </section>
    );
}
