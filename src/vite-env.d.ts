/// <reference types="vite/client" />

type PrismModule = typeof import('prismjs');

interface Window {
  pageLoadTime: number;
  Prism?: PrismModule;
  turnstile?: {
    render: (
      container: HTMLElement,
      options: {
        sitekey: string;
        theme?: 'light' | 'dark' | 'auto';
        callback?: () => void;
        'error-callback'?: () => void;
      }
    ) => string | number;
    getResponse: (widgetId?: string | number) => string;
    reset: (widgetId?: string | number) => void;
    remove: (widgetId?: string | number) => void;
  };
}

interface HTMLCanvasElement {
  __chartInstance?: {
    destroy?: () => void;
  };
}
