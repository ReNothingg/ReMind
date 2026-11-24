import type { components } from '../../generated/openapi';

export type SkillDocument = components['schemas']['AgentSkillDocument'];
export type ImportedSkill = components['schemas']['AgentSkillSummary'];

export const personalSkillEndpoint = '/api/agent/skills';
export const skillReferencePrefix = 'skill:';
export const maxMarkdownBytes = 64 * 1024;
export const maxArchiveBytes = 512 * 1024;
const skillName = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const languageHeader = /^(?:\uFEFF)?---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/;

function optionalText(header: Record<string, unknown>, key: string, max: number) {
  const value = header[key];
  if (value === undefined) return undefined;
  if (typeof value !== 'string' || !value.trim() || value.length > max)
    throw new Error('skill_invalid_document');
  return value.trim();
}

function flag(header: Record<string, unknown>, key: string) {
  const value = header[key];
  if (value !== undefined && typeof value !== 'boolean') throw new Error('skill_invalid_document');
  return value;
}

export async function parseSkillMarkdown(
  raw: string,
  resources: Record<string, string> = {}
): Promise<SkillDocument> {
  if (new TextEncoder().encode(raw).byteLength > maxMarkdownBytes)
    throw new Error('skill_package_too_large');
  const match = raw.match(languageHeader);
  if (!match?.[1] || new TextEncoder().encode(match[1]).byteLength > 8192)
    throw new Error('skill_invalid_document');
  const { parseDocument } = await import('yaml');
  const document = parseDocument(match[1], { strict: true, uniqueKeys: true, schema: 'core' });
  if (document.errors.length || document.warnings.length) throw new Error('skill_invalid_document');
  const read: unknown = document.toJS({ maxAliasCount: 0 });
  if (!read || typeof read !== 'object' || Array.isArray(read))
    throw new Error('skill_invalid_document');
  const header = read as Record<string, unknown>;
  const name = optionalText(header, 'name', 64);
  const description = optionalText(header, 'description', 1024);
  const body = raw.slice(match[0].length).trim();
  if (
    !name ||
    !skillName.test(name) ||
    name === 'compact' ||
    !description ||
    !body ||
    ['disableModelInvocation', 'modelInvocable', 'userInvocable'].some((key) =>
      Object.hasOwn(header, key)
    )
  ) {
    throw new Error('skill_invalid_document');
  }
  const whenToUse = optionalText(header, 'whenToUse', 500);
  const compatibility = optionalText(header, 'compatibility', 500);
  const license = optionalText(header, 'license', 250);
  return {
    name,
    description,
    body,
    resources,
    modelInvocable: flag(header, 'disable-model-invocation') !== true,
    userInvocable: flag(header, 'user-invocable') !== false,
    ...(whenToUse ? { whenToUse } : {}),
    ...(compatibility ? { compatibility } : {}),
    ...(license ? { license } : {}),
  };
}
