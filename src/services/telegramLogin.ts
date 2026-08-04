const TELEGRAM_LOGIN_SDK_ID = 'telegram-login-sdk';
const TELEGRAM_LOGIN_SDK_URL = 'https://oauth.telegram.org/js/telegram-login.js?3';
let telegramSdkPromise: Promise<void> | null = null;

export const loadTelegramLoginSdk = () => {
    if (window.Telegram?.Login) return Promise.resolve();
    if (telegramSdkPromise) return telegramSdkPromise;

    telegramSdkPromise = new Promise((resolve, reject) => {
        const existingScript = document.getElementById(TELEGRAM_LOGIN_SDK_ID) as HTMLScriptElement | null;
        const script = existingScript || document.createElement('script');

        const handleLoad = () => {
            if (window.Telegram?.Login) {
                resolve();
                return;
            }
            telegramSdkPromise = null;
            reject(new Error('telegram_sdk_unavailable'));
        };
        const handleError = () => {
            telegramSdkPromise = null;
            script.remove();
            reject(new Error('telegram_sdk_load_failed'));
        };

        script.addEventListener('load', handleLoad, { once: true });
        script.addEventListener('error', handleError, { once: true });
        if (!existingScript) {
            script.id = TELEGRAM_LOGIN_SDK_ID;
            script.src = TELEGRAM_LOGIN_SDK_URL;
            script.async = true;
            document.head.appendChild(script);
        }
    });

    return telegramSdkPromise;
};
