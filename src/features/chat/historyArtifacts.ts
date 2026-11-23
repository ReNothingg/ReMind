import type { CanvasTextdoc } from '../../services/api/types/chat';

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

export function normalizeCanvasTextdoc(value: unknown): CanvasTextdoc | null {
  if (!isRecord(value)) {
    return null;
  }

  const name = typeof value.name === 'string' ? value.name : '';
  const type = typeof value.type === 'string' ? value.type : '';
  if (!name || !type) {
    return null;
  }

  return {
    ...(typeof value.id === 'string' ? { id: value.id } : {}),
    name,
    type,
    content: typeof value.content === 'string' ? value.content : '',
    comments: Array.isArray(value.comments) ? value.comments : [],
    ...(typeof value.updated_at === 'number' ? { updated_at: value.updated_at } : {}),
  };
}

export function extractLatestCanvasTextdoc(messages: unknown): CanvasTextdoc | null {
  if (!Array.isArray(messages)) {
    return null;
  }

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const textdoc = normalizeCanvasTextdoc(
      messages[index]?.canvasTextdoc || messages[index]?.canvas_textdoc
    );
    if (textdoc) {
      return textdoc;
    }
  }

  return null;
}

export function normalizeBeatboxState(value: unknown) {
  if (!isRecord(value)) {
    return null;
  }

  const rawMeta = isRecord(value.meta) ? value.meta : {};
  const bpm = Math.max(40, Math.min(240, Number.parseInt(String(rawMeta.bpm), 10) || 120));
  const bars = Math.max(1, Math.min(16, Number.parseInt(String(rawMeta.bars), 10) || 1));
  const rawTracks = Array.isArray(value.tracks) ? value.tracks : [];
  const tracks = rawTracks
    .slice(0, 32)
    .map((track, index) => {
      if (!isRecord(track)) {
        return null;
      }
      const steps = Array.isArray(track.steps)
        ? track.steps.slice(0, bars * 16).map((step) => (step === 1 || step === true ? 1 : 0))
        : [];
      if (!steps.length) {
        return null;
      }
      const adsr = isRecord(track.adsr) ? track.adsr : {};
      return {
        id:
          typeof track.id === 'string' && track.id.trim()
            ? track.id.slice(0, 80)
            : `track_${index + 1}`,
        type: 'drum',
        drum:
          typeof track.drum === 'string' && track.drum.trim() ? track.drum.slice(0, 40) : 'kick',
        steps,
        adsr: {
          attack: Number.isFinite(Number(adsr.attack)) ? Number(adsr.attack) : 0.001,
          decay: Number.isFinite(Number(adsr.decay)) ? Number(adsr.decay) : 0.1,
          sustain: Number.isFinite(Number(adsr.sustain)) ? Number(adsr.sustain) : 0,
          release: Number.isFinite(Number(adsr.release)) ? Number(adsr.release) : 0.05,
        },
      };
    })
    .filter((track) => track !== null);

  if (!tracks.length) {
    return null;
  }

  return {
    meta: { bpm, bars },
    tracks,
    isPlaying: false,
    currentStep: 0,
    timerId: null,
  };
}

export function extractLatestBeatboxState(messages: unknown) {
  if (!Array.isArray(messages)) {
    return null;
  }

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message: unknown = messages[index];
    if (!isRecord(message)) continue;
    const texts: string[] = [];
    if (typeof message.content === 'string') texts.push(message.content);
    if (Array.isArray(message.parts)) {
      for (const part of message.parts) {
        if (isRecord(part) && typeof part.text === 'string') texts.push(part.text);
      }
    }
    for (const text of texts) {
      const matches = [...text.matchAll(/<beatbox>([\s\S]*?)<\/beatbox>/gi)];
      for (let matchIndex = matches.length - 1; matchIndex >= 0; matchIndex -= 1) {
        const encodedState = matches[matchIndex]?.[1];
        if (!encodedState) continue;
        try {
          const state = normalizeBeatboxState(JSON.parse(encodedState.trim()));
          if (state) {
            return state;
          }
        } catch {}
      }
    }

    const widgets = message.widgets;
    if (!Array.isArray(widgets)) {
      continue;
    }
    for (let widgetIndex = widgets.length - 1; widgetIndex >= 0; widgetIndex -= 1) {
      const widget = widgets[widgetIndex];
      if (isRecord(widget) && widget.type === 'beatbox') {
        const state = normalizeBeatboxState(widget.state);
        if (state) {
          return state;
        }
      }
    }
  }

  return null;
}
