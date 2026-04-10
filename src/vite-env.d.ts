/// <reference types="vite/client" />

type PrismModule = typeof import('prismjs');

interface Window {
  pageLoadTime: number;
  Prism?: PrismModule;
}

interface HTMLCanvasElement {
  __chartInstance?: {
    destroy?: () => void;
  };
}
