/// <reference types="vite/client" />

interface Window {
  pageLoadTime: number;
}

interface HTMLCanvasElement {
  __chartInstance?: {
    destroy?: () => void;
  };
}
