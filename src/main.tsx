import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { initI18n } from './i18n/index'
import './styles/variables.css'
import './styles/vendors/animate.css'
import './styles/components/auth/guest-mode.css'
import './styles/styles.css'
import './styles/components/modules/beatbox.css'
import './styles/components/ui/table.css'
import './styles/components/auth/auth.css'
import './styles/components/chat/code-block.css'
import './styles/components/ui/input.css'
import './styles/components/chat/prompt-suggestions.css'
import './styles/base/mobile.css'
import './styles/components/modules/quiz.css'
import './styles/components/ui/spinwheel.css'
import './styles/components/chat/formatter.css'
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
