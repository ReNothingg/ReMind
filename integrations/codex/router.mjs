import http from 'node:http';
import net from 'node:net';
import { lookup } from 'node:dns/promises';
import { default as https } from 'node:https';

const app = new URL(process.env.REMIND_APP_URL || 'http://app:5000');
const slots = (process.env.AGENT_SLOT_TARGETS || 'http://workspace-1:8092,http://workspace-2:8092')
  .split(',')
  .map((value) => new URL(value));
const allowed = new Set(
  (
    process.env.AGENT_EGRESS_HOSTS ||
    'auth.openai.com,api.openai.com,chatgpt.com,ab.chatgpt.com,cdn.openai.com'
  )
    .split(',')
    .map((x) => x.trim().toLowerCase())
);
const privateIPs = new net.BlockList();
for (const [ip, bits] of [
  ['0.0.0.0', 8],
  ['10.0.0.0', 8],
  ['100.64.0.0', 10],
  ['127.0.0.0', 8],
  ['169.254.0.0', 16],
  ['172.16.0.0', 12],
  ['192.0.0.0', 24],
  ['192.0.2.0', 24],
  ['192.168.0.0', 16],
  ['198.18.0.0', 15],
  ['198.51.100.0', 24],
  ['203.0.113.0', 24],
  ['224.0.0.0', 4],
  ['240.0.0.0', 4],
])
  privateIPs.addSubnet(ip, bits);
function clean(req, local = false) {
  const headers = { ...req.headers };
  for (const key of Object.keys(headers))
    if (
      key === 'proxy-authorization' ||
      key.startsWith('x-forwarded') ||
      key.startsWith('x-remind') ||
      key === 'forwarded'
    )
      delete headers[key];
  if (!local && headers.cookie)
    headers.cookie = String(headers.cookie)
      .split(';')
      .map((value) => value.trim())
      .filter((value) => /^(?:__Host-RemindAgent|RemindAgentDev)=/.test(value))
      .join('; ');
  if (local) {
    delete headers.cookie;
    headers.host = process.env.REMIND_INTERNAL_HOST || 'localhost';
    headers['x-forwarded-proto'] = 'https';
  }
  return headers;
}
function forward(req, res, target, path, headers) {
  const agent = target.protocol === 'https:' ? https : http;
  const upstream = agent.request(
    { hostname: target.hostname, port: target.port, path, method: req.method, headers },
    (reply) => {
      const responseHeaders = { ...reply.headers };
      if (target === app) delete responseHeaders['set-cookie'];
      res.writeHead(reply.statusCode || 502, responseHeaders);
      reply.pipe(res);
      reply.on('error', () => res.destroy());
    }
  );
  upstream.on('error', () => {
    if (!res.headersSent) res.writeHead(502);
    res.end();
  });
  res.on('close', () => upstream.destroy());
  req.pipe(upstream);
}
const internal = http.createServer((req, res) => {
  const path = req.url || '';
  if (/^\/control\/(?:public-key|rpc-check|cleanup)$/.test(path)) {
    if (path.includes('%') || path.includes('..') || path.includes('\\')) {
      res.writeHead(400);
      return res.end();
    }
    return forward(
      req,
      res,
      app,
      '/internal/agent/' + path.slice('/control/'.length),
      clean(req, true)
    );
  }
  const match = /^\/slots\/([1-9][0-9]{0,2})\/(.+)$/.exec(path);
  if (
    match &&
    req.method === 'POST' &&
    /^__agent\/(?:erase|codex\/(?:status|login|logout|cancel|turn|tool))$/.test(match[2]) &&
    slots[Number(match[1]) - 1]
  ) {
    const target = slots[Number(match[1]) - 1];
    return forward(req, res, target, '/' + match[2], { ...clean(req), host: target.host });
  }
  res.writeHead(404);
  res.end();
});
internal.on('connect', async (req, socket, head) => {
  let peer;
  try {
    const parts = /^([a-zA-Z0-9.-]+):443$/.exec(req.url || '');
    if (!parts || !allowed.has(parts[1].toLowerCase())) throw new Error();
    const addresses = await lookup(parts[1], { all: true, family: 4 });
    if (!addresses.length || addresses.some((x) => privateIPs.check(x.address, 'ipv4')))
      throw new Error();
    peer = net.connect(443, addresses[0].address, () => {
      socket.write('HTTP/1.1 200 Connection Established\r\n\r\n');
      if (head.length) peer.write(head);
      socket.pipe(peer).pipe(socket);
    });
    peer.setTimeout(180000, () => peer.destroy());
    peer.on('error', () => socket.destroy());
    socket.on('error', () => peer.destroy());
    socket.on('close', () => peer.destroy());
    peer.on('close', () => socket.destroy());
  } catch {
    peer?.destroy();
    socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');
  }
});
internal.listen(
  Number(process.env.REMIND_CONTROL_PORT || 8090),
  process.env.REMIND_CONTROL_BIND || '0.0.0.0'
);
