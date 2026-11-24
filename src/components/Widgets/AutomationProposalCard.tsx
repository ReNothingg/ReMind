import { useTranslation } from 'react-i18next';
import Pet from '../UI/Pet';

export default function AutomationProposalCard({
  state,
  ready,
}: {
  state: Record<string, unknown> | undefined;
  ready: boolean;
}) {
  const { t } = useTranslation();
  const id = state?.proposal_id;
  if (typeof id !== 'string' || !/^[a-f0-9]{32}$/.test(id)) return null;
  return (
    <section className="chat-tool-panel chat-tool-panel-automation">
      <h3 className="ui-pet-panel-heading">
        <Pet state="review" animate={!ready} />
        {t('automations.proposal.title')}
      </h3>
      {ready && <a href={`/automations?proposal=${id}`}>{t('automations.proposal.review')}</a>}
    </section>
  );
}
