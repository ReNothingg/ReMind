import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';
import ModalShell from '../../components/UI/ModalShell';
import type { components } from '../../generated/openapi';
import { apiService } from '../../services/api';
import type { ChatModel } from './modelSelection';

const sectionOrder = [
  'intent',
  'concepts',
  'files',
  'errors',
  'pending',
  'current',
  'next',
  'critical',
];

export default function ContextCheckpointModal({
  sessionId,
  models,
  onClose,
}: {
  sessionId: string;
  models: ChatModel[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const titleId = useId();
  const [checkpoint, setCheckpoint] = useState<
    components['schemas']['ChatContextCheckpoint'] | null
  >();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    apiService
      .getContextCheckpoint(sessionId, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setCheckpoint(result.checkpoint);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [sessionId]);

  const summary = checkpoint?.summary;
  const model = summary && models.find(({ id }) => id === summary.model);
  const modelName = model
    ? model.titleKey
      ? t(model.titleKey, { defaultValue: model.title })
      : model.title
    : '';

  return (
    <ModalShell
      ariaLabelledBy={titleId}
      contentClassName="chat-memory-dialog"
      onBackdropClick={onClose}
      onRequestClose={onClose}
    >
      <header className="chat-memory-header">
        <h2 id={titleId}>{t('chatMemory.view')}</h2>
        <button type="button" onClick={onClose} aria-label={t('common.close')}>
          <X size={19} aria-hidden="true" />
        </button>
      </header>
      <div className="chat-memory-body">
        {failed && <p role="alert">{t('chatMemory.readFailed')}</p>}
        {!failed && checkpoint === undefined && <p role="status">{t('common.loading')}</p>}
        {checkpoint === null && <p>{t('chatMemory.empty')}</p>}
        {!!checkpoint && (
          <>
            <p>{t('chatMemory.saved', { count: checkpoint.covered_messages })}</p>
            {modelName && <p>{t('chatMemory.sourceModel', { name: modelName })}</p>}
            {summary?.partial_history && <p>{t('chatMemory.partial')}</p>}
            {summary &&
              sectionOrder.map(
                (key) =>
                  summary.sections[key] && (
                    <section key={key}>
                      <h3>{t('chatMemory.sections.' + key)}</h3>
                      <p className="chat-memory-text">{summary.sections[key]}</p>
                    </section>
                  )
              )}
            {!summary &&
              checkpoint.excerpts.map((excerpt) => (
                <section key={excerpt.message}>
                  <h3>{t('chatMemory.excerpt', { number: excerpt.message })}</h3>
                  <blockquote className="chat-memory-text">{excerpt.quote}</blockquote>
                </section>
              ))}
          </>
        )}
      </div>
    </ModalShell>
  );
}
