import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

const backendTarget = process.env.VITE_BACKEND_URL || process.env.BACKEND_URL || 'http://127.0.0.1:5000'
const srcDir = fileURLToPath(new URL('./src', import.meta.url))
const nodeBuiltinBrowserStub = fileURLToPath(new URL('./src/utils/nodeBuiltinBrowserStub.ts', import.meta.url))
const backendProxy = {
  target: backendTarget,
  changeOrigin: true,
  secure: false,
  xfwd: true,
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": srcDir,
      "fs": nodeBuiltinBrowserStub,
      "path": nodeBuiltinBrowserStub,
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor': ['react', 'react-dom'],
          'markdown': ['markdown-it', 'prismjs', 'dompurify', 'katex']
        }
      }
    },
    chunkSizeWarningLimit: 1000
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/auth': backendProxy,
      '/api': {
        ...backendProxy,
      },
      '/chat': {
        ...backendProxy,
      },
      '/health': {
        ...backendProxy,
      },
      '/uploads': {
        ...backendProxy,
      },
      '/images': {
        ...backendProxy,
      },
      '/sessions': {
        ...backendProxy,
      },
      '/login': {
        ...backendProxy,
      },
      '/synthesize': {
        ...backendProxy,
      },
      '/translate': {
        ...backendProxy,
      },
      '/canvas-action': {
        ...backendProxy,
      },
    }
  }
})
