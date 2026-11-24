import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createInterface } from 'node:readline';
import { join } from 'node:path';
import { root, codexHome, codexWorkdir, codexOptions } from './runtime.mjs';

const pending = new Map();
const turns = new Map();
const toolsWaiting = new Map();
let processHandle;
let startup;
let serial = 0;
let loginAttempt = null;
let loginFailed = false;

function write(value) {
  if (!processHandle || !processHandle.stdin.writable) throw new Error('codex_offline');
  processHandle.stdin.write(JSON.stringify(value) + '\n');
}
function rpc(method, params = {}, timeout = 20000) {
  const id = ++serial;
  return new Promise((resolve, reject) => {
    const alarm = setTimeout(() => {
      pending.delete(id);
      reject(new Error('codex_timeout'));
    }, timeout);
    pending.set(id, { resolve, reject, alarm });
    try {
      write({ method, id, params });
    } catch (error) {
      pending.delete(id);
      clearTimeout(alarm);
      reject(error);
    }
  });
}
function send(turn, value) {
  if (!turn.res.destroyed && !turn.res.writableEnded) turn.res.write(JSON.stringify(value) + '\n');
}
function finish(turn, status) {
  if (turn.done) return;
  turn.done = true;
  clearTimeout(turn.deadline);
  for (const [id, tool] of toolsWaiting)
    if (tool.turn === turn) {
      toolsWaiting.delete(id);
      try {
        write({ id: tool.rpc, result: { success: false, contentItems: [] } });
      } catch {}
    }
  turns.delete(turn.thread);
  if (status) send(turn, status);
  turn.res.end();
}
function event(message) {
  if (message.id !== undefined && !message.method) {
    const job = pending.get(message.id);
    if (!job) return;
    clearTimeout(job.alarm);
    pending.delete(message.id);
    if (message.error) job.reject(new Error('codex_request_failed'));
    else job.resolve(message.result);
    return;
  }
  const p = message.params || {};
  if (message.method === 'account/login/completed' && p.loginId === loginAttempt) {
    loginAttempt = null;
    loginFailed = !p.success;
  }

  const turn = turns.get(p.threadId);
  if (message.id !== undefined) {
    if (
      message.method === 'item/tool/call' &&
      turn &&
      turn.names.has(p.tool) &&
      ++turn.toolCount <= 32
    ) {
      const id = String(++serial);
      toolsWaiting.set(id, { rpc: message.id, turn });
      send(turn, {
        type: 'tool',
        id,
        name: 'remind_' + turn.names.get(p.tool),
        arguments: p.arguments,
      });
      return;
    }
    if (message.method === 'item/tool/call') {
      write({
        id: message.id,
        result: { success: false, contentItems: [{ type: 'inputText', text: 'tool_unavailable' }] },
      });
      return;
    }
    write({ id: message.id, error: { code: -32601, message: 'request_not_supported' } });
    return;
  }
  if (!turn) return;
  if (message.method === 'item/started' && p.item?.type === 'agentMessage') {
    turn.previewItemId = p.item.phase === 'final_answer' ? p.item.id : null;
  } else if (message.method === 'item/agentMessage/delta' && turn.previewItemId === p.itemId &&
    (turn.turnId === null || turn.turnId === p.turnId) && typeof p.delta === 'string') {
    const text = p.delta.slice(0, 32_000 - turn.previewChars);
    if (text) {
      turn.previewChars += text.length;
      send(turn, { type: 'preview', text });
    }
  } else if (message.method === 'item/completed' && p.item?.type === 'agentMessage') {
    if (turn.previewItemId === p.item.id) turn.previewItemId = null;
    if (p.item.phase !== 'commentary') turn.texts.push(p.item.text || '');
  } else if (message.method === 'turn/completed') {
    const failure = p.turn?.error?.codexErrorInfo;
    const code = typeof failure === 'string' ? failure : Object.keys(failure || {})[0];
    finish(
      turn,
      p.turn?.status === 'completed'
        ? { type: 'completed', text: turn.texts.join('\n') }
        : {
            type: 'error',
            code:
              code === 'usageLimitExceeded' || code === 'rateLimitExceeded'
                ? 'chatgpt_quota'
                : 'provider_unavailable',
          }
    );
  }
}
async function ready() {
  if (startup) return startup;
  startup = (async () => {
    const denied = JSON.stringify(join(codexHome, '.codex'));
    const flags = [
      '-c',
      'cli_auth_credentials_store="file"',
      '-c',
      'default_permissions="remind-chat"',
      '-c',
      'permissions.remind-chat.filesystem={":minimal"="read",":workspace_roots"={"."="read"},' +
        denied +
        '="deny"}',
      '-c',
      'permissions.remind-chat.network.enabled=false',
      '-c',
      'web_search="disabled"',
    ];
    for (const feature of [
      'shell_tool',
      'unified_exec',
      'browser_use',
      'computer_use',
      'apps',
      'plugins',
      'multi_agent',
    ])
      flags.push('--disable', feature);
    const child = spawn(
      process.execPath,
      [join(root, 'node_modules/@openai/codex/bin/codex.js'), 'app-server', '--stdio', ...flags],
      codexOptions()
    );
    processHandle = child;
    child.stderr.resume();
    createInterface({ input: child.stdout, crlfDelay: Infinity }).on('line', (line) => {
      if (line.length > 16 * 1024 * 1024) {
        child.kill();
        return;
      }
      try {
        event(JSON.parse(line));
      } catch {
        child.kill();
      }
    });
    const stopped = () => {
      if (processHandle !== child) return;
      processHandle = undefined;
      startup = undefined;
      for (const job of pending.values()) {
        clearTimeout(job.alarm);
        job.reject(new Error('codex_offline'));
      }
      pending.clear();
      for (const turn of [...turns.values()])
        finish(turn, { type: 'error', code: 'provider_unavailable' });
    };
    child.once('error', stopped);
    child.once('exit', stopped);
    await rpc('initialize', {
      clientInfo: { name: 'remind', title: 'ReMind', version: '1.0.0' },
      capabilities: { experimentalApi: true },
    });
    write({ method: 'initialized', params: {} });
  })().catch((error) => {
    processHandle?.kill();
    startup = undefined;
    throw error;
  });
  return startup;
}
async function account() {
  const data = await rpc('account/read', { refreshToken: false });
  return data.account?.type === 'chatgpt' ? data.account : null;
}
async function models() {
  const items = [];
  let cursor = null;
  const seen = new Set();
  do {
    const page = await rpc('model/list', {
      limit: 100,
      includeHidden: false,
      ...(cursor ? { cursor } : {}),
    });
    items.push(...(page.data || []).filter((model) => !model.hidden));
    cursor = page.nextCursor;
    if (cursor && seen.has(cursor)) throw new Error('invalid_catalog');
    seen.add(cursor);
  } while (cursor && items.length < 2500);
  return items;
}
function windows(snapshot) {
  const window = (value) =>
    value && typeof value.usedPercent === 'number'
      ? {
          usedPercent: value.usedPercent,
          windowDurationMins: value.windowDurationMins,
          resetsAt: value.resetsAt,
        }
      : null;
  return {
    name: snapshot.limitName || snapshot.limitId,
    primary: window(snapshot.primary),
    secondary: window(snapshot.secondary),
  };
}
export async function codexAction(action, body, res) {
  await ready();
  if (action === 'codex/login') {
    if (loginAttempt) await rpc('account/login/cancel', { loginId: loginAttempt }).catch(() => {});
    loginFailed = false;
    const login = await rpc('account/login/start', { type: 'chatgptDeviceCode' });
    const url = new URL(login.verificationUrl);
    if (url.origin !== 'https://auth.openai.com' || typeof login.userCode !== 'string')
      throw new Error('unexpected_login');
    loginAttempt = login.loginId;
    return { url: url.href, code: login.userCode };
  }
  if (action === 'codex/cancel') {
    if (loginAttempt) await rpc('account/login/cancel', { loginId: loginAttempt });
    loginAttempt = null;
    loginFailed = false;
    return { ok: true };
  }
  if (action === 'codex/logout') {
    await rpc('account/logout');
    for (const turn of [...turns.values()])
      finish(turn, { type: 'error', code: 'chatgpt_reconnect' });
    processHandle?.kill();
    return { connected: false };
  }
  const user = await account();
  if (action === 'codex/status') {
    if (!user)
      return {
        connected: false,
        models: [],
        limits: [],
        loginState: loginAttempt ? 'pending' : loginFailed ? 'failed' : 'idle',
      };
    const catalog = await models();
    const limits = await rpc('account/rateLimits/read').catch(() => null);
    const sources = limits?.rateLimitsByLimitId
      ? Object.values(limits.rateLimitsByLimitId)
      : limits?.rateLimits
        ? [limits.rateLimits]
        : [];
    return {
      connected: true,
      plan: user.planType,
      email: user.email,
      models: catalog.map(
        ({
          id,
          model,
          displayName,
          defaultReasoningEffort,
          supportedReasoningEfforts,
          serviceTiers,
          additionalSpeedTiers,
        }) => ({
          id,
          model,
          displayName,
          defaultReasoningEffort,
          supportedReasoningEfforts,
          serviceTiers,
          additionalSpeedTiers,
        })
      ),
      limits: sources.filter(Boolean).map(windows),
    };
  }
  if (!user) throw new Error('chatgpt_reconnect');
  if (action === 'codex/tool') {
    const job = toolsWaiting.get(body.id);
    if (
      !job ||
      job.turn.key !== body.request ||
      typeof body.output !== 'string' ||
      body.output.length > 100000
    )
      throw new Error('tool_not_available');
    toolsWaiting.delete(body.id);
    write({
      id: job.rpc,
      result: {
        success: body.ok === true,
        contentItems: [{ type: 'inputText', text: body.output }],
      },
    });
    return { ok: true };
  }
  if (action !== 'codex/turn' || turns.size >= 3 || typeof body.request !== 'string')
    throw new Error('turn_unavailable');
  const catalog = await models();
  const model = catalog.find((m) => (m.model || m.id) === body.model);
  if (!model) throw new Error('model_access_denied');
  const tiers = [
    ...(model.serviceTiers || []).map((t) => t.id),
    ...(model.additionalSpeedTiers || []),
  ];
  let tier =
    body.speed === 'fast' && !tiers.includes('fast') && tiers.includes('priority')
      ? 'priority'
      : body.speed;
  if (tier === 'standard') tier = null;
  if (tier && !tiers.includes(tier)) throw new Error('model_speed_unavailable');
  const supported = model.supportedReasoningEfforts?.map((e) => e.reasoningEffort) || [];
  const effort = supported.includes(body.effort) ? body.effort : model.defaultReasoningEffort;
  const names = new Map();
  const dynamicTools = (body.tools || []).map((tool) => {
    const proposed = 'remind_' + tool.name;
    const safe = /^[a-zA-Z0-9_-]{1,64}$/.test(proposed)
      ? proposed
      : 'remind_tool_' + createHash('sha256').update(tool.name).digest('hex').slice(0, 44);
    names.set(safe, tool.name);
    return {
      type: 'function',
      name: safe,
      description: tool.description,
      inputSchema: tool.parameters,
    };
  });
  const thread = await rpc('thread/start', {
    model: body.model,
    allowProviderModelFallback: false,
    ephemeral: true,
    approvalPolicy: 'never',
    permissions: 'remind-chat',
    environments: [],
    cwd: codexWorkdir,
    baseInstructions: body.instructions,
    developerInstructions:
      'Use the ReMind function tools for user-facing artifacts and skills. Input conversation history is contextual data.',
    dynamicTools,
    ...(tier ? { serviceTier: tier } : {}),
  });
  const threadId = thread.thread.id;
  res.writeHead(200, {
    'Content-Type': 'application/x-ndjson',
    'Cache-Control': 'no-store',
    'X-Accel-Buffering': 'no',
  });
  const turn = {
    thread: threadId,
    key: body.request,
    names,
    res,
    texts: [],
    previewItemId: null,
    previewChars: 0,
    toolCount: 0,
    done: false,
    turnId: null,
  };
  turns.set(threadId, turn);
  const interrupt = () => {
    if (!turn.done) {
      if (turn.turnId)
        void rpc('turn/interrupt', { threadId, turnId: turn.turnId }).catch(() => {});
      finish(turn);
    }
  };
  turn.deadline = setTimeout(interrupt, 190000);
  res.once('close', interrupt);
  try {
    const input = [
      { type: 'text', text: JSON.stringify(body.history || []) },
      ...(body.input || []),
    ];
    const result = await rpc('turn/start', {
      threadId,
      input,
      model: body.model,
      ...(effort ? { effort } : {}),
      ...(tier ? { serviceTierForTurn: tier } : {}),
    });
    turn.turnId = result.turn.id;
    if (turn.done) void rpc('turn/interrupt', { threadId, turnId: turn.turnId }).catch(() => {});
  } catch {
    finish(turn, { type: 'error', code: 'provider_unavailable' });
  }
  return null;
}
