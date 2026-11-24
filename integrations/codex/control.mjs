import { createPublicKey, verify } from 'node:crypto';

export const slotId = Number(process.env.REMIND_SLOT_ID || '1');
export const controlOrigin = new URL(
  process.env.REMIND_CONTROL_URL || 'http://agent-router:8090/control/'
);
let publicKey;

export async function control(path, token, body = {}) {
  const response = await fetch(new URL(path, controlOrigin), {
    method: 'POST',
    redirect: 'error',
    signal: AbortSignal.timeout(10000),
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error('workspace_session_expired');
  return response.json();
}

export async function claims(token, scope) {
  if (typeof token !== 'string' || token.length > 12000) throw new Error('invalid_grant');
  const parts = token.split('.');
  if (parts.length !== 3) throw new Error('invalid_grant');
  if (!publicKey) {
    const response = await fetch(new URL('public-key', controlOrigin), {
      redirect: 'error',
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error('control_unavailable');
    publicKey = createPublicKey(await response.text());
  }
  if (
    !verify(
      null,
      Buffer.from(parts[0] + '.' + parts[1]),
      publicKey,
      Buffer.from(parts[2], 'base64url')
    )
  )
    throw new Error('invalid_grant');
  const data = JSON.parse(Buffer.from(parts[1], 'base64url'));
  const now = Date.now() / 1000;
  if (
    data.iss !== 'remind-workspace' ||
    data.aud !== 'remind-agent-slot' ||
    data.scope !== scope ||
    data.slot !== slotId ||
    !Number.isSafeInteger(data.gen) ||
    !Number.isFinite(data.exp) ||
    data.exp <= now ||
    !Number.isFinite(data.iat) ||
    data.iat > now + 30 ||
    !/^[a-f0-9]{32}$/.test(data.sub)
  )
    throw new Error('invalid_grant');
  return data;
}

export function bearer(req) {
  const value = req.headers.authorization || '';
  return value.startsWith('Bearer ') ? value.slice(7) : '';
}

export async function readJson(req, limit = 16 * 1024 * 1024) {
  let size = 0;
  const chunks = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw new Error('body_limit');
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}');
}

export function json(res, status, data) {
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  });
  res.end(JSON.stringify(data));
}
