import { isKnownComposerTool, toolIconPath } from './composerTools';

export function renderComposerMentions(html: string, labelFor: (id: string) => string): string {
  const root = document.createElement('div');
  root.innerHTML = html;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  for (const node of nodes) {
    const value = node.data;
    const fragment = document.createDocumentFragment();
    let from = 0;
    for (const match of value.matchAll(/@\{([a-z_]+)\}/g)) {
      const id = match[1];
      if (!id || !isKnownComposerTool(id) || match.index === undefined) continue;
      fragment.append(document.createTextNode(value.slice(from, match.index)));
      const token = document.createElement('span');
      token.className = 'message-tool-mention';
      token.dataset.toolId = id;
      const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      for (const [key, value] of Object.entries({
        viewBox: '0 0 24 24',
        width: '18',
        height: '18',
        fill: 'none',
        stroke: 'currentColor',
        'stroke-width': '2',
        'aria-hidden': 'true',
      }))
        icon.setAttribute(key, value);
      const path = document.createElementNS(icon.namespaceURI, 'path');
      path.setAttribute('d', toolIconPath(id));
      icon.append(path);
      token.append(icon, document.createTextNode(labelFor(id)));
      fragment.append(token);
      from = match.index + match[0].length;
    }
    if (from) {
      fragment.append(document.createTextNode(value.slice(from)));
      node.replaceWith(fragment);
    }
  }
  return root.innerHTML;
}
