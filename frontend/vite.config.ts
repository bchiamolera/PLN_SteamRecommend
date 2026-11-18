import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'STEAM_ATLAS_');
  const target = env.STEAM_ATLAS_API_TARGET || 'http://127.0.0.1:8000';
  if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(target)) {
    throw new Error('STEAM_ATLAS_API_TARGET must be a local HTTP address and port.');
  }
  const proxy = { '/api': { target, timeout: 0, proxyTimeout: 0 } };
  return { plugins: [react()], server: { host: '127.0.0.1', proxy }, preview: { host: '127.0.0.1', proxy } };
});
