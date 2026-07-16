import { useEffect, useRef } from 'react';
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
import {
    bracketMatching,
    codeFolding,
    foldGutter,
    foldKeymap,
    HighlightStyle,
    indentOnInput,
    LanguageDescription,
    syntaxHighlighting,
} from '@codemirror/language';
import { languages } from '@codemirror/language-data';
import { Compartment, EditorState } from '@codemirror/state';
import {
    drawSelection,
    dropCursor,
    EditorView,
    highlightActiveLine,
    highlightActiveLineGutter,
    highlightSpecialChars,
    keymap,
    lineNumbers,
    placeholder,
    rectangularSelection,
} from '@codemirror/view';
import { tags } from '@lezer/highlight';

type CanvasCodeEditorProps = {
    value: string;
    language: string;
    filename: string;
    ariaLabel: string;
    emptyText: string;
    collapseLabel: string;
    expandLabel: string;
    onChange: (value: string) => void;
    onBlur: () => void;
};

const languageNameAliases: Record<string, string> = {
    bash: 'Shell',
    csharp: 'C#',
    cpp: 'C++',
    docker: 'Dockerfile',
    markup: 'HTML',
    powershell: 'PowerShell',
    shellscript: 'Shell',
    tsx: 'TSX',
};

const canvasHighlightStyle = HighlightStyle.define([
    { tag: tags.comment, color: 'var(--code-token-comment)' },
    { tag: tags.keyword, color: 'var(--code-token-keyword)' },
    { tag: [tags.string, tags.special(tags.string)], color: 'var(--code-token-string)' },
    { tag: [tags.number, tags.bool, tags.null], color: 'var(--code-token-number)' },
    { tag: [tags.function(tags.variableName), tags.function(tags.propertyName)], color: 'var(--code-token-function)' },
    { tag: [tags.typeName, tags.className, tags.namespace], color: 'var(--code-token-class-name)' },
    { tag: [tags.propertyName, tags.attributeName], color: 'var(--code-token-property)' },
    { tag: [tags.operator, tags.punctuation], color: 'var(--code-token-operator)' },
    { tag: [tags.regexp, tags.escape], color: 'var(--code-token-regex)' },
    { tag: [tags.invalid, tags.deleted], color: 'var(--code-token-deleted)' },
    { tag: tags.inserted, color: 'var(--code-token-inserted)' },
    { tag: [tags.heading, tags.strong], color: 'var(--code-token-important)', fontWeight: '700' },
]);

function findLanguage(filename: string, language: string): LanguageDescription | null {
    const byFilename = filename
        ? LanguageDescription.matchFilename(languages, filename)
        : null;
    if (byFilename) return byFilename;

    const normalized = language.trim().toLowerCase();
    const languageName = languageNameAliases[normalized] || language;
    return LanguageDescription.matchLanguageName(languages, languageName, true);
}

function createFoldMarker(open: boolean, collapseLabel: string, expandLabel: string): HTMLElement {
    const marker = document.createElement('span');
    const label = open ? collapseLabel : expandLabel;
    marker.className = `chat-canvas-fold-marker ${open ? 'is-open' : 'is-closed'}`;
    marker.setAttribute('aria-label', label);
    marker.setAttribute('title', label);
    return marker;
}

function createFoldPlaceholder(
    expandLabel: string,
    onclick: (event: Event) => void
): HTMLElement {
    const placeholderElement = document.createElement('span');
    placeholderElement.className = 'cm-foldPlaceholder';
    placeholderElement.textContent = '…';
    placeholderElement.setAttribute('aria-label', expandLabel);
    placeholderElement.setAttribute('title', expandLabel);
    placeholderElement.onclick = onclick;
    return placeholderElement;
}

const CanvasCodeEditor = ({
    value,
    language,
    filename,
    ariaLabel,
    emptyText,
    collapseLabel,
    expandLabel,
    onChange,
    onBlur,
}: CanvasCodeEditorProps) => {
    const hostRef = useRef<HTMLDivElement | null>(null);
    const viewRef = useRef<EditorView | null>(null);
    const languageCompartmentRef = useRef(new Compartment());
    const valueRef = useRef(value);
    const onChangeRef = useRef(onChange);
    const onBlurRef = useRef(onBlur);

    useEffect(() => {
        onChangeRef.current = onChange;
        onBlurRef.current = onBlur;
    }, [onBlur, onChange]);

    useEffect(() => {
        const host = hostRef.current;
        if (!host) return undefined;

        const state = EditorState.create({
            doc: valueRef.current,
            extensions: [
                lineNumbers(),
                highlightActiveLineGutter(),
                foldGutter({
                    markerDOM: (open) => createFoldMarker(
                        open,
                        collapseLabel,
                        expandLabel
                    ),
                }),
                highlightSpecialChars(),
                history(),
                drawSelection(),
                dropCursor(),
                EditorState.allowMultipleSelections.of(true),
                EditorState.tabSize.of(2),
                indentOnInput(),
                syntaxHighlighting(canvasHighlightStyle),
                bracketMatching(),
                codeFolding({
                    placeholderDOM: (_view, onclick) => createFoldPlaceholder(
                        expandLabel,
                        onclick
                    ),
                }),
                rectangularSelection(),
                highlightActiveLine(),
                keymap.of([
                    indentWithTab,
                    ...defaultKeymap,
                    ...historyKeymap,
                    ...foldKeymap,
                ]),
                placeholder(emptyText),
                languageCompartmentRef.current.of([]),
                EditorView.contentAttributes.of({
                    'aria-label': ariaLabel,
                    autocapitalize: 'off',
                    autocorrect: 'off',
                    spellcheck: 'false',
                }),
                EditorView.domEventHandlers({
                    blur: () => {
                        onBlurRef.current();
                        return false;
                    },
                }),
                EditorView.updateListener.of((update) => {
                    if (!update.docChanged) return;
                    const nextValue = update.state.doc.toString();
                    if (nextValue === valueRef.current) return;
                    valueRef.current = nextValue;
                    onChangeRef.current(nextValue);
                }),
            ],
        });

        const view = new EditorView({ state, parent: host });
        viewRef.current = view;
        return () => {
            viewRef.current = null;
            view.destroy();
        };
    }, [ariaLabel, collapseLabel, emptyText, expandLabel]);

    useEffect(() => {
        const view = viewRef.current;
        if (!view) return;
        const currentValue = view.state.doc.toString();
        if (currentValue === value) {
            valueRef.current = value;
            return;
        }

        valueRef.current = value;
        view.dispatch({
            changes: { from: 0, to: currentValue.length, insert: value },
        });
    }, [value]);

    useEffect(() => {
        const view = viewRef.current;
        if (!view) return undefined;
        let cancelled = false;
        const description = findLanguage(filename, language);

        if (!description) {
            view.dispatch({
                effects: languageCompartmentRef.current.reconfigure([]),
            });
            return undefined;
        }

        void description.load().then((support) => {
            if (cancelled || viewRef.current !== view) return;
            view.dispatch({
                effects: languageCompartmentRef.current.reconfigure(support),
            });
        }).catch(() => {
            // Keep the editor usable as plain text if a language chunk cannot load.
        });

        return () => {
            cancelled = true;
        };
    }, [filename, language]);

    return <div ref={hostRef} className="chat-canvas-codemirror" />;
};

export default CanvasCodeEditor;
