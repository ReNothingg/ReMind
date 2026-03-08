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
    navigator.serviceWorker
      .register('/sw.js')
      .catch(() => {
      });
  });
}
