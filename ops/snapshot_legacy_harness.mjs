import { readFileSync, readdirSync, lstatSync } from 'node:fs';
import { basename, join } from 'node:path';
import { zstdDecompressSync } from 'node:zlib';

const root = '/data/home/.dsh';
const slot = Number(process.env.REMIND_SLOT_ID);
const lease = JSON.parse(readFileSync('/data/.lease.json', 'utf8'));
if (!Number.isInteger(slot) || slot < 1 || !/^[a-f0-9]{32}$/.test(lease.workspace ?? '') ||
    !Number.isInteger(lease.generation) || lease.erase)
  throw new Error('Legacy workspace slot is unassigned');

const counts = {
  logs: 0, blank: 0, invalid: 0, archived: 0, attachments: 0, projects: 0, chats: 0,
};
const projects = new Map();
const ownership = new Map();
let archived = new Set();

function output(value) {
  process.stdout.write(JSON.stringify(value) + '\n');
}

function entries(directory) {
  try {
    if (!lstatSync(directory).isDirectory()) return [];
    return readdirSync(directory, { withFileTypes: true });
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }
}

function registryPath(directory, depth = 0) {
  for (const item of entries(directory)) {
    const path = join(directory, item.name);
    if (item.isFile() && item.name === 'workspace.json') return path;
    if (depth < 3 && item.isDirectory() && !['sessions', 'cache', 'node_modules'].includes(item.name)) {
      const found = registryPath(path, depth + 1);
      if (found) return found;
    }
  }
}

function parseRegistry() {
  const path = registryPath(root);
  if (!path) return;
  if (lstatSync(path).size > 4 * 1024 * 1024) throw new Error('Legacy registry is too large');
  const registry = JSON.parse(readFileSync(path, 'utf8'));
  if (!registry.tables?.workspaces || !Array.isArray(registry.global?.workspaceIds)) {
    throw new Error('Unsupported legacy workspace registry');
  }
  archived = new Set(Array.isArray(registry.global.archivedSessionIds) ? registry.global.archivedSessionIds : []);
  for (const id of registry.global.workspaceIds) {
    const project = registry.tables.workspaces[id];
    if (!project || typeof project.title !== 'string' || !Array.isArray(project.sessionIds)) continue;
    const key = 'workspace:' + id;
    projects.set(key, { key, name: project.title, createdAt: project.createdAt });
    for (const session of project.sessionIds) ownership.set(session, key);
  }
}

function logicalMessages(log) {
  const surface = [];
  let title = '';
  for (const event of log) {
    if (event.type === 'session/title' && typeof event.data?.title === 'string')
      title = event.data.title;
    if (!['user/message', 'assistant/message'].includes(event.type)) continue;
    const content = event.type === 'assistant/message' ? event.data?.message?.content : event.data?.content;
    if (!Array.isArray(content)) continue;
    const text = content.filter((part) => part.type === 'text' && typeof part.text === 'string')
      .map((part) => part.text).join('');
    counts.attachments += content.filter((part) => ['image', 'file', 'attachment'].includes(part.type)).length;
    const row = {
      at: event.time,
      seq: event.seq,
      role: event.type === 'assistant/message' ? 'model' : 'user',
      text,
      ...(typeof event.data?.message?.source?.model === 'string'
        ? { model: event.data.message.source.model }
        : {}),
    };
    if (event.surfaceOp?.op === 'replace') {
      const start = surface.findIndex((item) => item.seq === event.surfaceOp.startSeq);
      const end = surface.findIndex((item) => item.seq === event.surfaceOp.endSeq);
      if (start < 0 || end < start) throw new Error('Invalid legacy replacement');
      surface.splice(start, end - start + 1, row);
    } else {
      surface.push(row);
    }
  }
  return { title, messages: surface.filter((item) => item.text.trim()) };
}

const artifact = /^session(?:\.v([0-9]+))?\.jsonl(?:\.zstd)?$/;
function journals() {
  const sessions = join(root, 'sessions');
  const result = [];
  for (const group of entries(sessions).filter((item) => item.isDirectory())) {
    const directory = join(sessions, group.name);
    for (const session of entries(directory).filter((item) => item.isDirectory())) {
      const location = join(directory, session.name);
      const options = entries(location)
        .filter((item) => item.isFile() && artifact.test(item.name))
        .sort((a, b) => Number(b.name.match(artifact)[1] || 0) - Number(a.name.match(artifact)[1] || 0));
      if (options.length) result.push(join(location, options[0].name));
    }
  }
  return result;
}

function readLog(path) {
  if (lstatSync(path).size > 16 * 1024 * 1024) throw new Error('Legacy log is too large');
  const raw = readFileSync(path);
  const data = (path.endsWith('.zstd') ? zstdDecompressSync(raw, { maxOutputLength: 32 * 1024 * 1024 }) : raw).toString('utf8');
  const parts = data.split('\n');
  if (!data.endsWith('\n')) parts.pop();
  const [header, ...log] = parts.filter(Boolean).map((line) => JSON.parse(line));
  if (header?.type !== 'session' || header.version !== 4 || typeof header.id !== 'string') {
    throw new Error('Unsupported legacy session format');
  }
  return { header, log };
}

parseRegistry();
output({ record: 'slot', slot, workspace: lease.workspace, generation: lease.generation });
const outputProjects = new Set();
function emitProject(key) {
  if (!key || outputProjects.has(key)) return;
  const project = projects.get(key);
  if (!project) return;
  output({ record: 'project', ...project });
  outputProjects.add(key);
  counts.projects++;
}
for (const key of projects.keys()) emitProject(key);
for (const path of journals()) {
  counts.logs++;
  try {
    const { header, log } = readLog(path);
    if (archived.has(header.id)) { counts.archived++; continue; }
    if (header.delegationDepth > 0) { counts.blank++; continue; }
    const result = logicalMessages(log);
    if (!result.messages.length) { counts.blank++; continue; }
    let key = ownership.get(header.id);
    if (!key && typeof header.cwd === 'string' && header.cwd) {
      key = 'directory:' + header.cwd;
      if (!projects.has(key)) projects.set(key, {
        key, name: basename(header.cwd) || 'Workspace', createdAt: header.createdAt,
      });
      emitProject(key);
    }
    output({ record: 'chat', id: header.id, project: key ?? null, createdAt: header.createdAt, ...result });
    counts.chats++;
  } catch {
    counts.invalid++;
  }
}
output({ record: 'end', counts });
