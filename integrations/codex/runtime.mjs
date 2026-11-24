import { mkdir, readFile, rename, rm, writeFile, chown } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { claims, control, slotId } from './control.mjs';

export const root = fileURLToPath(new URL('.', import.meta.url));
const data = process.env.REMIND_SLOT_DATA || '/data';
export const codexHome = join(data, 'codex-home');
export const codexWorkdir = join(codexHome, 'workspace');
const statePath = join(data, '.lease.json');
const privileged = process.getuid?.() === 0;
let state;
let mutations = Promise.resolve();

export function codexOptions() {
  const env = {
    PATH: '/usr/local/bin:/usr/bin:/bin',
    LANG: 'C.UTF-8',
    HOME: codexHome,
    XDG_CACHE_HOME: join(codexHome, '.cache'),
  };
  if (process.env.REMIND_EGRESS_PROXY) {
    env.HTTPS_PROXY = process.env.REMIND_EGRESS_PROXY;
    env.HTTP_PROXY = process.env.REMIND_EGRESS_PROXY;
    env.NO_PROXY = '127.0.0.1,localhost';
  }
  return {
    cwd: codexWorkdir,
    stdio: ['pipe', 'pipe', 'pipe'],
    env,
    ...(privileged ? { uid: 1002, gid: 1002 } : {}),
  };
}

function serialized(action) {
  const running = mutations.then(action);
  mutations = running.catch(() => {});
  return running;
}

async function save(next) {
  const pending = statePath + '.tmp';
  await writeFile(pending, JSON.stringify(next), { mode: 0o600 });
  await rename(pending, statePath);
  state = next;
}

export async function initialize() {
  await mkdir(data, { recursive: true, mode: 0o711 });
  try {
    state = JSON.parse(await readFile(statePath, 'utf8'));
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  if (state?.erase) {
    await rm(codexHome, { recursive: true, force: true });
    await rm(join(data, 'home'), { recursive: true, force: true });
    await rm(join(data, 'managed-skills'), { recursive: true, force: true });
    await rm(join(data, '.managed-profile.yml'), { force: true });
    await save({ generation: state.generation });
  }
}

export function attach(proof) {
  return serialized(async () => {
    if (
      state?.erase ||
      (state && proof.gen < state.generation) ||
      (state?.workspace && proof.gen === state.generation && proof.sub !== state.workspace)
    )
      throw new Error('invalid_grant');
    if (state?.workspace && state.workspace !== proof.sub) {
      await save({ ...state, erase: true });
      setTimeout(() => process.exit(75), 75).unref();
      throw new Error('workspace_restarting');
    }
    if (!state?.workspace) {
      await mkdir(codexWorkdir, { recursive: true, mode: 0o700 });
      if (privileged) {
        await chown(codexHome, 1002, 1002);
        await chown(codexWorkdir, 1002, 1002);
      }
      await save({ workspace: proof.sub, generation: proof.gen });
    }
  });
}

export function erase(proof) {
  return serialized(async () => {
    if (proof.gen !== state?.generation || proof.sub !== state.workspace) return;
    await save({ ...state, erase: true });
    setTimeout(() => process.exit(75), 75).unref();
  });
}

export async function checkRetirement() {
  if (!state?.workspace || state.erase) return;
  const answer = await control('cleanup', '', {
    slot: slotId,
    workspace: state.workspace,
    generation: state.generation,
  });
  if (!answer.instruction) return;
  const proof = await claims(answer.instruction, 'rpc');
  if (proof.op === 'erase') await erase(proof);
}
