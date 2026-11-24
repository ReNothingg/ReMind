import { useEffect, useId, useState } from 'react';
import { Check, MessageSquare, Search, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import ModalShell from '../../components/UI/ModalShell';
import type { components } from '../../generated/openapi';
import { fetchApi } from '../../services/api/transport';
import './chat-references.css';

export type ChatReference = components['schemas']['ChatReference'];
type Candidates = components['schemas']['ChatReferenceCandidates'];
export const maxChatReferences = 3;

export default function ChatReferencePicker({ current, project, selected, onChange, onClose }: {
  current?: string | null;
  project?: string | null;
  selected: ChatReference[];
  onChange: (choices: ChatReference[]) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const titleId = useId();
  const [query, setQuery] = useState('');
  const [revision, setRevision] = useState(0);
  const search = query.trim();
  const [result, setResult] = useState<{ query: string; revision: number; choices: ChatReference[] | null }>();
  const choices = result?.query === search && result.revision === revision ? result.choices : undefined;

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams();
    if (current) params.set('session_id', current);
    if (project) params.set('workspace_id', project);
    if (search) params.set('q', search);
    const timer = window.setTimeout(() => {
      fetchApi<Candidates>('/api/chat-references?' + params.toString(), { signal: controller.signal })
        .then(({ chats }) => {
          if (!controller.signal.aborted) setResult({ query: search, revision, choices: chats });
        })
        .catch(() => {
          if (!controller.signal.aborted) setResult({ query: search, revision, choices: null });
        });
    }, search ? 180 : 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [current, project, revision, search]);

  function toggle(choice: ChatReference) {
    if (selected.some((item) => item.session_id === choice.session_id)) {
      onChange(selected.filter((item) => item.session_id !== choice.session_id));
    } else if (selected.length < maxChatReferences) {
      onChange([...selected, choice]);
    }
  }

  return (
    <ModalShell ariaLabelledBy={titleId} contentClassName="ui-modal-card chat-reference-picker" onRequestClose={onClose}>
      <header>
        <h2 id={titleId}>{t('chatReferences.title')}</h2>
        <button type="button" onClick={onClose} aria-label={t('common.close')}>
          <X size={18} aria-hidden="true" />
        </button>
      </header>
      <label className="chat-reference-search">
        <Search size={17} aria-hidden="true" />
        <input type="search" aria-label={t('chatReferences.search')} placeholder={t('chatReferences.search')}
          value={query} maxLength={120} onChange={(event) => setQuery(event.target.value)} />
      </label>
      <div className="chat-reference-results" aria-busy={choices === undefined}>
        {choices === undefined && <p role="status">{t('common.loading')}</p>}
        {choices === null && <p role="alert">{t('chatReferences.loadFailed')}</p>}
        {choices?.length === 0 && <p>{t(search ? 'chatReferences.noResults' : 'chatReferences.empty')}</p>}
        {choices?.map((choice) => {
          const chosen = selected.some((item) => item.session_id === choice.session_id);
          return (
            <button type="button" key={choice.session_id} aria-pressed={chosen}
              disabled={!chosen && selected.length >= maxChatReferences} onClick={() => toggle(choice)}>
              <MessageSquare size={17} aria-hidden="true" />
              <span>
                <strong>{choice.title || t('chatReferences.untitled')}</strong>
                <small>{choice.workspace_name || t('chatReferences.personal')}</small>
              </span>
              {chosen && <Check size={17} aria-hidden="true" />}
            </button>
          );
        })}
      </div>
      <footer>
        <span aria-live="polite">{t('chatReferences.count', { selected: selected.length, max: maxChatReferences })}</span>
        {choices === null && (
          <button className="ui-button-secondary" type="button" onClick={() => setRevision((value) => value + 1)}>{t('chatReferences.retry')}</button>
        )}
        <button className="ui-button-secondary" type="button" onClick={onClose}>{t('chatReferences.done')}</button>
      </footer>
    </ModalShell>
  );
}
