import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef } from 'react';
import {
  Compartment,
  EditorState,
  Prec,
  StateEffect,
  StateField,
  Transaction,
} from '@codemirror/state';
import {
  Decoration,
  EditorView,
  WidgetType,
  keymap,
  placeholder,
  type DecorationSet,
} from '@codemirror/view';
import { defaultKeymap, history, historyKeymap, isolateHistory } from '@codemirror/commands';

import { toolMarker, toolIconPath, type ComposerTool } from '../composerTools';

export interface ComposerTextEditorHandle {
  focus(): void;
  insertTool(from: number, to: number, id: string): void;
}

interface Props {
  value: string;
  tools: ComposerTool[];
  placeholder: string;
  label: string;
  readOnly: boolean;
  menuId?: string | undefined;
  activeOptionId?: string | undefined;
  descriptionId?: string | undefined;
  onChange(value: string, caret: number): void;
  onSelection(value: string, caret: number): void;
  onKeyDown(event: KeyboardEvent): void;
  onPaste(event: ClipboardEvent): void;
  onBlur(): void;
  onHeightChange(height: number, unwrappedWidth: number): void;
}

const refreshTools = StateEffect.define<void>();

class ToolWidget extends WidgetType {
  constructor(readonly tool: ComposerTool) {
    super();
  }
  eq(other: ToolWidget) {
    return (
      this.tool.id === other.tool.id &&
      this.tool.label === other.tool.label &&
      this.tool.removeLabel === other.tool.removeLabel
    );
  }
  toDOM(view: EditorView): HTMLElement {
    const element = document.createElement('span');
    element.className = 'composer-inline-tool';
    element.dataset.toolId = this.tool.id;
    element.setAttribute('role', 'button');
    element.setAttribute('aria-label', this.tool.removeLabel);
    element.title = this.tool.removeLabel;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [name, value] of Object.entries({
      viewBox: '0 0 24 24',
      width: '18',
      height: '18',
      fill: 'none',
      stroke: 'currentColor',
      'stroke-width': '2',
      'aria-hidden': 'true',
    })) {
      svg.setAttribute(name, value);
    }
    const path = document.createElementNS(svg.namespaceURI, 'path');
    path.setAttribute('d', toolIconPath(this.tool.id));
    svg.append(path);
    const label = document.createElement('span');
    label.textContent = this.tool.label;
    element.append(svg, label);
    element.addEventListener('mousedown', (event) => event.preventDefault());
    element.addEventListener('click', () => {
      if (view.state.readOnly) return;
      const from = view.posAtDOM(element);
      const marker = toolMarker(this.tool.id);
      if (view.state.sliceDoc(from, from + marker.length) !== marker) return;
      view.dispatch({
        changes: { from, to: from + marker.length, insert: '' },
        selection: { anchor: from },
        userEvent: 'delete',
        annotations: isolateHistory.of('full'),
      });
      view.focus();
    });
    return element;
  }
}

export const ComposerTextEditor = forwardRef<ComposerTextEditorHandle, Props>(
  function ComposerTextEditor(props, ref) {
    const hostRef = useRef<HTMLDivElement>(null);
    const viewRef = useRef<EditorView | null>(null);
    const propsRef = useRef(props);
    const optionsRef = useRef(new Compartment());
    useLayoutEffect(() => {
      propsRef.current = props;
    });

    useImperativeHandle(
      ref,
      () => ({
        focus: () => viewRef.current?.focus(),
        insertTool: (from, to, id) => {
          const view = viewRef.current;
          if (
            !view ||
            view.state.readOnly ||
            !propsRef.current.tools.some((tool) => tool.id === id)
          )
            return;

          const existingSpace = view.state.sliceDoc(to, to + 1) === ' ';
          const insert = toolMarker(id) + (existingSpace ? '' : ' ');
          view.dispatch({
            changes: { from, to, insert },
            selection: { anchor: from + insert.length + (existingSpace ? 1 : 0) },
            userEvent: 'input.complete',
            annotations: isolateHistory.of('full'),
          });
          view.focus();
        },
      }),
      []
    );

    useLayoutEffect(() => {
      if (!hostRef.current) return;
      const decorate = (state: EditorState) => {
        const ranges = [];
        const source = state.doc.toString();
        for (const match of source.matchAll(/@\{([a-z_]+)\}/g)) {
          const tool = propsRef.current.tools.find((candidate) => candidate.id === match[1]);
          if (tool && match.index !== undefined) {
            ranges.push(
              Decoration.replace({ widget: new ToolWidget(tool) }).range(
                match.index,
                match.index + match[0].length
              )
            );
          }
        }
        return Decoration.set(ranges);
      };
      const tokens = StateField.define<DecorationSet>({
        create: decorate,
        update: (value, transaction) =>
          transaction.docChanged || transaction.effects.some((effect) => effect.is(refreshTools))
            ? decorate(transaction.state)
            : value,
        provide: (field) => [
          EditorView.decorations.from(field),
          EditorView.atomicRanges.of((view) => view.state.field(field)),
        ],
      });
      const canvas = document.createElement('canvas').getContext('2d');
      const measureKey = {};
      const measure = (editor: EditorView) =>
        editor.requestMeasure({
          key: measureKey,
          read: () => {
            const style = getComputedStyle(editor.contentDOM);
            let width = 0;
            if (canvas) {
              canvas.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
              const source = editor.state.doc.toString() || propsRef.current.placeholder;
              let from = 0;
              for (const match of source.matchAll(/@\{([a-z_]+)\}/g)) {
                const tool = propsRef.current.tools.find((candidate) => candidate.id === match[1]);
                if (!tool || match.index === undefined) continue;
                width += canvas.measureText(source.slice(from, match.index)).width;
                width += canvas.measureText(tool.label).width + 28;
                from = match.index + match[0].length;
              }
              width += canvas.measureText(source.slice(from)).width;
            }
            return {
              height: editor.dom.offsetHeight,
              width: editor.state.doc.lines > 1 ? Infinity : width,
            };
          },
          write: ({ height, width }) => propsRef.current.onHeightChange(height, width),
        });
      const view = new EditorView({
        parent: hostRef.current,
        state: EditorState.create({
          doc: propsRef.current.value,
          extensions: [
            tokens,
            history(),
            EditorView.lineWrapping,
            optionsRef.current.of([]),
            Prec.highest(
              EditorView.domEventHandlers({
                keydown: (event) => {
                  propsRef.current.onKeyDown(event);
                  return event.defaultPrevented;
                },
                paste: (event) => {
                  propsRef.current.onPaste(event);
                  return event.defaultPrevented;
                },
                blur: () => {
                  propsRef.current.onBlur();
                },
              })
            ),
            keymap.of([...defaultKeymap, ...historyKeymap]),
            EditorView.updateListener.of((update) => {
              const value = update.state.doc.toString();
              const caret = update.state.selection.main.head;
              if (update.docChanged) {
                propsRef.current.onChange(value, caret);
                measure(update.view);
              } else if (update.selectionSet) propsRef.current.onSelection(value, caret);
            }),
          ],
        }),
      });
      viewRef.current = view;
      const observer = new ResizeObserver(() => measure(view));
      observer.observe(view.dom);
      return () => {
        observer.disconnect();
        view.destroy();
        viewRef.current = null;
      };
    }, []);

    useLayoutEffect(() => {
      const view = viewRef.current;
      if (view && view.state.doc.toString() !== props.value) {
        view.dispatch({
          changes: { from: 0, to: view.state.doc.length, insert: props.value },
          annotations: Transaction.addToHistory.of(false),
        });
      }
    }, [props.value]);

    const toolSignature = JSON.stringify(props.tools);
    useEffect(() => {
      viewRef.current?.dispatch({ effects: refreshTools.of() });
    }, [toolSignature]);
    useLayoutEffect(() => {
      viewRef.current?.dispatch({
        effects: optionsRef.current.reconfigure([
          EditorState.readOnly.of(props.readOnly),
          EditorView.editable.of(!props.readOnly),
          placeholder(props.placeholder),
          EditorView.contentAttributes.of({
            id: 'promptInput',
            role: 'textbox',
            'aria-multiline': 'true',
            'aria-label': props.label,
            'aria-expanded': String(!!props.menuId),
            'aria-autocomplete': 'list',
            ...(props.menuId ? { 'aria-controls': props.menuId } : {}),
            ...(props.activeOptionId ? { 'aria-activedescendant': props.activeOptionId } : {}),
            ...(props.descriptionId ? { 'aria-describedby': props.descriptionId } : {}),
          }),
        ]),
      });
    }, [
      props.readOnly,
      props.placeholder,
      props.label,
      props.menuId,
      props.activeOptionId,
      props.descriptionId,
    ]);
    return <div ref={hostRef} className="composer-rich-editor" />;
  }
);
