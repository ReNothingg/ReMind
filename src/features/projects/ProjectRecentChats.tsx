import { MessageCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { SessionSummary } from '../sessions/hooks/useSessionList';

export default function ProjectRecentChats({
  sessions,
  onOpen,
}: {
  sessions: SessionSummary[];
  onOpen: (sessionId: string) => void;
}) {
  const { t } = useTranslation();
  if (!sessions.length) return null;

  return (
    <section className="project-home-chats" aria-label={t('projects.recentChats')}>
      <h2>{t('projects.recentChats')}</h2>
      <ul>
        {sessions.map((item) => (
          <li key={item.session_id}>
            <button type="button" onClick={() => onOpen(item.session_id)}>
              <MessageCircle size={16} aria-hidden="true" />
              <span>{item.title || t('rail.newChat')}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
