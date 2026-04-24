import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { initI18n } from './i18n/index'
import './styles/tailwind.css'
if (!sessionStorage.getItem('userID')) {
    sessionStorage.setItem('userID', `uid_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`);
}
window.pageLoadTime = Date.now();

const rootElement = document.getElementById('root');

const renderApp = () => {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
};

initI18n().then(renderApp).catch(renderApp);
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    const isLocalHttp =
      window.location.protocol === 'http:' &&
      ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname);

    if (isLocalHttp) {
      navigator.serviceWorker
        .getRegistrations()
        .then((registrations) => Promise.all(registrations.map((registration) => registration.unregister())))
        .then(() => caches.keys())
        .then((keys) => Promise.all(keys.filter((key) => key.startsWith('remind-')).map((key) => caches.delete(key))))
        .catch(() => {
        });
      return;
    }

    navigator.serviceWorker
      .register('/sw.js')
      .catch(() => {
      });
  });
}
