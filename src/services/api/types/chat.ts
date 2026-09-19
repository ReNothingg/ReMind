
export type ChatWidgetUpdate = Record<string, unknown>;

export type ChatThinkingUpdate = {
    id?: string;
    status?: 'streaming' | 'complete' | string;
    contentDelta?: string;
    openTime?: number;
    closeTime?: number;
};

export type CanvasTextdocComment = {
    id?: string;
    pattern: string;
    comment: string;
    created_at?: number;
};

export type CanvasTextdoc = {
    id?: string;
    name: string;
    type: string;
    content: string;
    comments?: CanvasTextdocComment[];
    updated_at?: number;
};

export type CanvasUpdate = {
    action?: string;
    events?: unknown[];
    textdoc?: CanvasTextdoc | null;
};

export type ChatStreamResult = {
    aborted?: boolean;
    canvas_textdoc?: CanvasTextdoc | null;
    canvas_update?: CanvasUpdate;
    canvas_updates?: CanvasUpdate[];
    canvasTextdoc?: CanvasTextdoc | null;
    end_of_stream?: boolean;
    images?: string[] | string;
    reply?: string;
    reply_part?: string;
    sessionId?: string;
    sessionSlug?: string;
    sources?: unknown[];
    status?: string;
    thinkingTime?: number;
    thinking_update?: ChatThinkingUpdate;
    widget_update?: ChatWidgetUpdate;
    [key: string]: unknown;
};

export type ChatCallbacks = {
    onError?: (error: Error) => void;
    onComplete?: (data: ChatStreamResult) => void;
    onCanvasUpdate?: (data: CanvasUpdate) => void;
    onPart?: (data: ChatStreamResult) => void;
    onWidgetUpdate?: (widgetData: ChatWidgetUpdate) => void;
    onOpen?: (data: { requestId: string; sessionToken: string }) => void;
};

export type CanvasSaveResponse = {
    session_id?: string;
    textdoc: CanvasTextdoc;
};

export type CanvasPythonExecutionResponse = {
    ok: boolean;
    error?: string;
    exit_code?: number | null;
    timed_out?: boolean;
    duration_ms?: number;
    stdout?: string;
    stderr?: string;
    stdout_truncated?: boolean;
    stderr_truncated?: boolean;
    artifacts?: CanvasPythonArtifact[];
};

export type CanvasPythonArtifact = {
    original_name?: string;
    mime_type?: string;
    size?: number;
    metadata?: Record<string, unknown>;
    data_url?: string;
};

export type CanvasActionResponse = Record<string, unknown>;
