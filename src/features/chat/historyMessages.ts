import type { components } from '../../generated/openapi';
import { isKnownComposerTool } from './composerTools';
import { normalizeCanvasTextdoc } from './historyArtifacts';

type ChatMessage = components['schemas']['ChatMessage'];

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function normalizeHistoryImage(value: unknown) {
  if (typeof value === 'string') return value;
  if (!isRecord(value)) return '';
  const urlPath = value.url_path || value.url || value.path || '';
  if (typeof urlPath !== 'string' || !urlPath) return '';
  const hasArtifactShape = Boolean(
    value.original_name && value.mime_type && Number.isFinite(Number(value.size))
  );
  return {
    url_path: urlPath,
    original_name: value.original_name || value.name || undefined,
    mime_type: value.mime_type || undefined,
    source: value.source === 'python' || hasArtifactShape ? 'python' : undefined,
    metadata: value.metadata && typeof value.metadata === 'object' ? value.metadata : undefined,
  };
}

function normalizeHistoryVariant(value: unknown) {
  if (!isRecord(value)) return null;
  const parts = Array.isArray(value.parts) ? value.parts.filter(isRecord) : [];
  const text = parts.find((part) => typeof part.text === 'string')?.text;
  const content =
    typeof value.content === 'string' ? value.content : typeof text === 'string' ? text : '';
  return {
    id: value.variant_id || value.id || crypto.randomUUID(),
    variantId: value.variant_id || value.id || null,
    content,
    images: parts
      .filter((part) => part?.image)
      .map((part) => normalizeHistoryImage(part.image))
      .filter(Boolean),
    files: parts.filter((part) => part?.file).map((part) => ({ file: part.file })),
    sources: Array.isArray(value.sources) ? value.sources : [],
    githubTool: value.github_tool || value.githubTool || null,
    canvasTextdoc: normalizeCanvasTextdoc(value.canvas_textdoc || value.canvasTextdoc),
    canvasUpdates: Array.isArray(value.canvas_updates || value.canvasUpdates)
      ? value.canvas_updates || value.canvasUpdates
      : [],
    composerContent: value.composer_content || value.composerContent,
    selectedTools: value.selected_tools || value.selectedTools || [],
    modelId: value.model_id || value.modelId,
    thinkingTime: value.thinkingTime,
    contextUsage: value.context_usage || value.contextUsage,
    timestamp: value.timestamp,
    deliveryState: value.delivery_status === 'interrupted' ? 'interrupted' : undefined,
    parts,
  };
}

export function normalizeHistoryMessage(
  msg: ChatMessage,
  index?: number,
  messages?: Array<Record<string, unknown>>
) {
  const parts = Array.isArray(msg.parts) ? msg.parts.filter(isRecord) : [];
  const firstText = parts.find((part) => typeof part.text === 'string' && part.text)?.text;
  let text = typeof firstText === 'string' ? firstText : '';

  if (text.trim().startsWith('{') && text.trim().endsWith('}')) {
    try {
      const parsed = JSON.parse(text);
      if (parsed.url_path || parsed.original_name || parsed.mime_type) {
        text = '';
      }
    } catch {}
  }

  text = text.replace(/---\s*File:\s*[^-\n]+---[\s\S]*?---\s*End\s*File\s*---/gi, '');
  text = text.replace(/\[Binary\s+file:[^\]]+\]/gi, '');

  const images = parts.map((part) => normalizeHistoryImage(part.image)).filter(Boolean);
  const files = parts.flatMap((part) => {
    if (!part.file) return [];
    const file = isRecord(part.file) ? part.file : {};
    return [
      {
        file: {
          url_path: file.url_path || part.file,
          original_name: file.original_name || file.name || 'file',
          mime_type: file.mime_type || 'application/octet-stream',
          size: file.size || 0,
        },
      },
    ];
  });

  const variants = Array.isArray(msg.variants)
    ? msg.variants.map(normalizeHistoryVariant).filter((variant) => variant !== null)
    : [];
  const requestedVariantIndex = Number(msg.current_variant_index ?? msg.currentVariantIndex ?? 0);
  const currentVariantIndex = variants.length
    ? Math.max(
        0,
        Math.min(
          Number.isFinite(requestedVariantIndex) ? requestedVariantIndex : 0,
          variants.length - 1
        )
      )
    : undefined;
  const currentVariant = currentVariantIndex !== undefined ? variants[currentVariantIndex] : null;

  const followingReply = index !== undefined ? messages?.[index + 1] : undefined;
  const legacyTools = Array.isArray(followingReply?.selected_tools)
    ? followingReply.selected_tools.filter(
        (id): id is string => typeof id === 'string' && isKnownComposerTool(id)
      )
    : [];
  if (followingReply?.model_id === 'demo_image' || followingReply?.model_id === 'mindart')
    legacyTools.push(followingReply.model_id);

  return {
    toolBadges: msg.role === 'user' ? [...new Set(legacyTools)] : [],
    id: msg.id || Math.random().toString(36).substr(2, 9),
    role: msg.role,
    composerContent: currentVariant
      ? currentVariant.composerContent
      : msg.composer_content || msg.composerContent,
    selectedTools: currentVariant?.selectedTools || msg.selected_tools || msg.selectedTools || [],
    modelId: currentVariant?.modelId || msg.model_id || msg.modelId,
    contextUsage: currentVariant
      ? currentVariant.contextUsage
      : msg.context_usage || msg.contextUsage,
    content: currentVariant?.content ?? text.trim(),
    images: currentVariant?.images ?? images,
    files: currentVariant?.files?.length ? currentVariant.files : files,
    sources: currentVariant?.sources ?? (Array.isArray(msg.sources) ? msg.sources : []),
    githubTool: currentVariant?.githubTool || msg.github_tool || msg.githubTool || null,
    canvasTextdoc:
      currentVariant?.canvasTextdoc ||
      normalizeCanvasTextdoc(msg.canvas_textdoc || msg.canvasTextdoc),
    canvasUpdates:
      currentVariant?.canvasUpdates ??
      (Array.isArray(msg.canvas_updates || msg.canvasUpdates)
        ? msg.canvas_updates || msg.canvasUpdates
        : []),
    timestamp: currentVariant?.timestamp ?? msg.timestamp,
    deliveryState:
      currentVariant?.deliveryState ??
      (msg.delivery_status === 'interrupted' ? 'interrupted' : undefined),
    parts: currentVariant?.parts ?? parts,
    variants,
    currentVariantIndex,
  };
}
