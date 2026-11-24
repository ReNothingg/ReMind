import { createServer } from 'node:http';
import { bearer, claims, control, json, readJson } from './control.mjs';
import { codexAction } from './codex.mjs';
import { attach, checkRetirement, erase, initialize } from './runtime.mjs';

const operations = new Set([
  'codex/status',
  'codex/login',
  'codex/logout',
  'codex/cancel',
  'codex/turn',
  'codex/tool',
]);
const errors = {
  workspace_restarting: 503,
  chatgpt_reconnect: 401,
  model_speed_unavailable: 400,
  model_access_denied: 403,
  chatgpt_quota: 429,
};
await initialize();
const clean = () => void checkRetirement().catch(() => {});
clean();
setInterval(clean, 60000).unref();

createServer(async (req, res) => {
  try {
    if (req.url === '/health' && req.method === 'GET') return json(res, 200, { ready: true });
    const operation = req.url?.startsWith('/__agent/') ? req.url.slice(9) : '';
    if (!(operations.has(operation) || operation === 'erase') || req.method !== 'POST')
      return json(res, 404, { error: 'not_found' });
    const token = bearer(req);
    const proof = await claims(token, 'rpc');
    if (proof.op !== operation) throw new Error('invalid_grant');
    if (operation === 'erase') {
      await erase(proof);
      return json(res, 200, { ok: true });
    }
    await control('rpc-check', token);
    await attach(proof);
    const result = await codexAction(operation, await readJson(req), res);
    if (result !== null) json(res, 200, result);
  } catch (error) {
    if (res.headersSent) return res.destroy();
    const known = errors[error.message];
    json(res, known || 403, { error: known ? error.message : 'workspace_session_expired' });
  }
}).listen(
  Number(process.env.REMIND_SLOT_PORT || '8092'),
  process.env.REMIND_SLOT_BIND || '0.0.0.0'
);
