/// <reference types="vite/client" />

type PrismModule = typeof import('prismjs');

interface Window {
  pageLoadTime: number;
  openHtmlPreviewModal?: (urlOrHtml: string, isHtml?: boolean) => void;
  closeHtmlPreviewModal?: () => void;
  openImageLightbox?: (imageSrc: string, messageId?: string) => void;
  closeImageLightbox?: () => void;
  webkitAudioContext?: typeof AudioContext;
  Prism?: PrismModule;
  turnstile?: {
    render: (
      container: HTMLElement,
      options: {
        sitekey: string;
        theme?: 'light' | 'dark' | 'auto';
        size?: 'normal' | 'flexible' | 'compact';
        appearance?: 'always' | 'execute' | 'interaction-only';
        execution?: 'render' | 'execute';
        callback?: (token: string) => void;
        'error-callback'?: (errorCode?: string) => void;
        'expired-callback'?: () => void;
      }
    ) => string | number;
    getResponse: (widgetId?: string | number) => string;
    reset: (widgetId?: string | number) => void;
    remove: (widgetId?: string | number) => void;
  };
  webkit?: {
    messageHandlers?: {
      remindMacBridge?: {
        postMessage: (message: unknown) => void;
      };
    };
  };
}

interface Navigator {
  userAgentData?: {
    platform?: string;
  };
}

interface HTMLCanvasElement {
  __chartInstance?: {
    destroy?: () => void;
  };
}
