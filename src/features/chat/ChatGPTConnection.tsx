import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MessageCircle } from 'lucide-react';
import { fetchApi } from '../../services/api/transport';
import type { components } from '../../generated/openapi';

type Account = components['schemas']['ChatGPTAccount'];

export default function ChatGPTConnection() {
  const { t } = useTranslation();
  const [account, setAccount] = useState<Account | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    fetchApi<Account>('/api/chatgpt')
      .then((value) => {
        if (active) {
          setAccount(value);
          if (value.login_error) setMessage('chatgptAccount.failed');
        }
      })
      .catch(() => {
        if (active) setMessage('chatgptAccount.failed');
      });
    return () => {
      active = false;
    };
  }, [revision]);

  const connect = async (differentAccount = false) => {
    setBusy(true);
    setMessage('');
    try {
      const result = await fetchApi<{ url: string }>('/api/chatgpt/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ different_account: differentAccount }),
      });
      const url = new URL(result.url);
      if (url.origin !== 'https://auth.openai.com' || url.pathname !== '/api/accounts/authorize')
        throw new Error();
      window.location.assign(url.href);
    } catch {
      setMessage('chatgptAccount.failed');
      setBusy(false);
    }
  };
  const disconnect = async () => {
    setBusy(true);
    try {
      const result = await fetchApi<{ revoked: boolean }>('/api/chatgpt', { method: 'DELETE' });
      setAccount(
        (previous) =>
          previous && { ...previous, connected: false, consent_required: false, email: null }
      );
      setMessage(result.revoked ? '' : 'chatgptAccount.revocation');
      window.dispatchEvent(new Event('remind:model-catalog'));
    } catch {
      setMessage('chatgptAccount.failed');
    } finally {
      setBusy(false);
    }
  };
  const localOrigin =
    account?.origin &&
    /^http:\/\/127\.0\.0\.1(?::\d+)?$/.test(account.origin) &&
    account.origin !== window.location.origin
      ? account.origin
      : null;
  return (
    <div className="account-connected-app-row chatgpt-connection">
      <span className="account-connected-app-icon" aria-hidden="true">
        <MessageCircle size={21} />
      </span>
      <div className="account-connected-app-copy">
        <strong>{t('chatgptAccount.title')}</strong>
        <span>
          {account?.connected
            ? account.email
            : t(
                account && !account.configured
                  ? 'chatgptAccount.unconfigured'
                  : account?.consent_required
                    ? 'chatgptAccount.consent'
                    : 'chatgptAccount.description'
              )}
        </span>
        {message && (
          <span role="status" className="account-connected-app-error">
            {t(message)}
          </span>
        )}
        {(account?.connected || message === 'chatgptAccount.revocation') && (
          <a href="https://chatgpt.com/settings/usage" target="_blank" rel="noreferrer">
            {t('chatgptAccount.usage')}
          </a>
        )}
      </div>
      <div className="account-connected-app-controls">
        {!account && message ? (
          <button
            type="button"
            className="account-connected-app-action ui-button-secondary"
            onClick={() => {
              setMessage('');
              setRevision((value) => value + 1);
            }}
          >
            {t('chatgptAccount.retry')}
          </button>
        ) : (
          <>
            {localOrigin && !account?.connected && (
              <a
                className="account-connected-app-action ui-button-secondary"
                href={localOrigin + '/#settings/models'}
              >
                {t('chatgptAccount.local')}
              </a>
            )}
            {!localOrigin && !account?.connected && (
              <button
                type="button"
                className="account-connected-app-action ui-button-secondary"
                disabled={!account?.configured || busy}
                onClick={() => void connect()}
              >
                {t('chatgptAccount.connect')}
              </button>
            )}
            {!localOrigin &&
              account?.registered &&
              !account.connected &&
              !account.consent_required && (
                <button
                  type="button"
                  className="account-connected-app-action ui-button-secondary"
                  disabled={busy}
                  onClick={() => void connect(true)}
                >
                  {t('chatgptAccount.switch')}
                </button>
              )}
            {(account?.connected || account?.consent_required) && (
              <button
                type="button"
                className="account-connected-app-action ui-button-secondary"
                disabled={busy}
                onClick={() => void disconnect()}
              >
                {t('chatgptAccount.disconnect')}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
