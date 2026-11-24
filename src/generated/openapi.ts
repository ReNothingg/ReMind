export interface components {
  schemas: {
    AgentBuiltinPlugin: {
      description_key: string | null;
      enabled: boolean;
      id: string;
      title_key: string | null;
    };
    AgentCustomPlugin: {
      description: string;
      enabled: boolean;
      id: string;
      instructions: string;
      kind: "custom";
      name: string;
      skills: string[];
      version: string;
    };
    AgentPluginManifest: {
      description: string;
      id: string;
      instructions: string;
      name: string;
      skills: string[];
      version: string;
    };
    AgentProviderCatalogMode: "provider" | "custom";
    AgentProviderConnection: {
      baseUrl: string;
      catalogMode: components["schemas"]["AgentProviderCatalogMode"];
      connected: boolean;
      custom: boolean;
      defaultBaseUrl: string;
      id: string;
      modelCount: number;
      models: components["schemas"]["AgentProviderModel"][];
      name: string;
      protocol: "openai-completions" | "openai-responses" | "anthropic-messages" | "google-generative-ai";
      reasoningLevels?: components["schemas"]["ModelReasoningLevel"][];
      retryPolicy?: components["schemas"]["ProviderRetryPolicy"];
      revision: components["schemas"]["AgentProviderRevision"];
    };
    AgentProviderConnections: {
      providers: components["schemas"]["AgentProviderConnection"][];
    };
    AgentProviderModel: {
      contextWindow?: number;
      inputModalities?: ("text" | "image")[];
      maxTokens?: number;
      reasoningEfforts?: false | {
        high?: string;
        low?: string;
        max?: string;
        medium?: string;
        minimal?: string;
        none?: string | null;
        off?: string | null;
        ultra?: string;
        xhigh?: string;
      };
      slug: string;
      title: string;
    };
    AgentProviderRevision: string | null;
    AgentProviderWriteCondition: {
      expectedRevision?: components["schemas"]["AgentProviderRevision"];
    };
    AgentRuntimeSettings: {
      contextCompaction: "automatic" | "manual";
      contextHeadroomTokens: number;
      contextRetainPercent: number;
      contextRetainTokens: number;
      contextSummaryMode: "excerpts" | "model";
      contextSummaryModel: string;
      contextSummaryRetries: number;
      contextSummaryTokens: number;
      contextThresholdPercent: number;
      maxSteps: number;
      maxToolCalls: number;
      maxToolCallsPerStep: number;
      modelReplayEnabled: boolean;
      shellEnabled: boolean;
      shellMaxOutputBytes: number;
      shellTimeoutMs: number;
      subagentAllowedModels: string[];
      subagentMaxActive: number;
      subagentMaxDepth: number;
      subagentModel: string;
      subagentModelSelection: boolean;
      toolTimeSeconds: number;
    };
    AgentSkillCatalog: {
      skills: components["schemas"]["AgentSkillSummary"][];
    };
    AgentSkillDocument: {
      body: string;
      compatibility?: string;
      description: string;
      license?: string;
      modelInvocable?: boolean;
      name: string;
      resources?: Record<string, string>;
      userInvocable?: boolean;
      whenToUse?: string;
    };
    AgentSkillInspectionResult: {
      skill: components["schemas"]["AgentSkillSummary"] | {
        body: string;
        resources: string[];
        scripts?: string[];
      };
    };
    AgentSkillResult: {
      skill: components["schemas"]["AgentSkillSummary"];
    };
    AgentSkillSummary: {
      compatibility?: string;
      description: string;
      enabled: boolean;
      id: string;
      license?: string;
      modelInvocable: boolean;
      name: string;
      resourceCount: number;
      scriptCount?: number;
      userInvocable: boolean;
      whenToUse?: string;
    };
    AgentWebResearchSettings: {
      fetchBilling: "linked" | "dedicated";
      fetchProvider: "remind" | "deepseek-fetch-api";
      hasDedicatedKey: boolean;
      hasLinkedKey: boolean;
      legacyMaxUses: number;
      searchBilling: "linked" | "dedicated";
      searchCount: number;
      searchProvider: "remind" | "deepseek-search-api" | "deepseek-legacy";
    };
    AgentWebResearchUpdate: {
      clearKey?: boolean;
      fetchBilling?: "linked" | "dedicated";
      fetchProvider?: "remind" | "deepseek-fetch-api";
      key?: string;
      legacyMaxUses?: number;
      searchBilling?: "linked" | "dedicated";
      searchCount?: number;
      searchProvider?: "remind" | "deepseek-search-api" | "deepseek-legacy";
    };
    AppleChallengeResponse: {
      challenge: string;
      expires_in: number;
      nonce: string;
    };
    AppleLoginRequest: {
      challenge: string;
      identity_token: string;
      name?: {
        first_name?: string | null;
        last_name?: string | null;
        middle_name?: string | null;
      } | null;
    };
    AuthCheckResponse: {
      authenticated: boolean;
      user: components["schemas"]["User"] | null;
    };
    AuthConfigResponse: {
      apple_login_url?: string | null;
      apple_native_available?: boolean;
      apple_web_available?: boolean;
      gauth_available?: boolean;
      google_login_url?: string;
      telegram_available?: boolean;
      turnstile_required?: boolean;
      turnstile_site_key?: string | null;
      [key: string]: unknown;
    };
    AuthErrorResponse: {
      error: string;
      [key: string]: unknown;
    };
    AuthLoginRequest: {
      email: string;
      password: string;
      turnstile_response?: string | null;
    };
    AuthLoginResponse: {
      message: string;
      user: components["schemas"]["User"];
    };
    AutomationCreate: {
      enabled?: boolean;
      model: string;
      prompt: string;
      target_session_id?: string | null;
      timing: components["schemas"]["AutomationTiming"];
      title: string;
      web_search?: boolean;
      workspace_id?: string | null;
    };
    AutomationProposal: {
      applied_at: string | null;
      changes: components["schemas"]["AutomationUpdate"];
      id: string;
      operation: "create" | "edit" | "pause" | "resume" | "run" | "delete";
      result: {
        removed?: boolean;
        run?: components["schemas"]["AutomationRun"];
        task_id?: string;
      } | null;
      stale: boolean;
      task: components["schemas"]["AutomationTask"] | null;
    };
    AutomationRun: {
      error: string | null;
      finished_at: string | null;
      id: string;
      occurrence_at: string;
      queued_at: string;
      session_id: string | null;
      started_at: string | null;
      status: "queued" | "running" | "completed" | "failed" | "cancelled";
    };
    AutomationTask: {
      created_at: string;
      enabled: boolean;
      id: string;
      last_run: components["schemas"]["AutomationRun"] | null;
      model: string;
      next_run_at: string | null;
      prompt: string;
      target_session_id: string | null;
      timing: components["schemas"]["AutomationTiming"];
      title: string;
      web_search: boolean;
      workspace_id: string | null;
    };
    AutomationTiming: {
      at: string;
      kind: "at";
    } | {
      kind: "after";
      seconds: number;
    } | {
      kind: "every";
      seconds: number;
    } | {
      kind: "daily";
      time: string;
      zone: string;
    } | {
      kind: "weekly";
      time: string;
      weekdays: number[];
      zone: string;
    } | {
      day: number;
      kind: "monthly";
      time: string;
      zone: string;
    } | {
      expression: string;
      kind: "cron";
      zone: string;
    };
    AutomationUpdate: {
      enabled?: boolean;
      model?: string;
      prompt?: string;
      target_session_id?: string | null;
      timing?: components["schemas"]["AutomationTiming"];
      title?: string;
      web_search?: boolean;
      workspace_id?: string | null;
    };
    CanvasPythonExecuteRequest: {
      code: string;
    };
    CanvasPythonExecuteResponse: {
      duration_ms?: number;
      error?: string | null;
      exit_code?: number | null;
      ok: boolean;
      request_id?: string | null;
      stderr?: string;
      stderr_truncated?: boolean;
      stdout?: string;
      stdout_truncated?: boolean;
      timed_out?: boolean;
    };
    CanvasSaveRequest: {
      textdoc: components["schemas"]["CanvasTextdoc"];
    };
    CanvasSaveResponse: {
      ok: boolean;
      request_id?: string | null;
      session_id: string;
      textdoc: components["schemas"]["CanvasTextdoc"];
    };
    CanvasTextdoc: {
      comments?: Record<string, unknown>[];
      content: string;
      id?: string;
      name: string;
      type: string;
      updated_at?: number;
    };
    ChatContextCheckpoint: {
      covered_messages: number;
      excerpts: ({
        excerpt: boolean;
        message: number;
        quote: string;
        role: "user" | "model";
      })[];
      summary?: {
        model: string;
        partial_history: boolean;
        sections: Record<string, string>;
      };
    };
    ChatDraft: {
      content: string;
      device_id: string;
      revision: number;
      session_id?: string | null;
      updated_at: number;
    };
    ChatDraftRequest: {
      base_revision?: number | null;
      content: string;
      device_id: string;
      session_id?: string | null;
    };
    ChatDraftResponse: {
      draft?: components["schemas"]["ChatDraft"] | null;
      error?: string;
      [key: string]: unknown;
    };
    ChatGPTAccount: {
      configured: boolean;
      connected: boolean;
      consent_required: boolean;
      email?: string | null;
      login_error: boolean;
      origin: string | null;
      registered: boolean;
    };
    ChatMessage: {
      chat_references?: components["schemas"]["ChatReference"][];
      composer_content?: string;
      context_usage?: components["schemas"]["ContextUsage"];
      current_variant_index?: number;
      delivery_status?: "complete" | "interrupted" | null;
      id?: string | null;
      is_active?: boolean;
      model_id?: string;
      parent_id?: string | null;
      parts: components["schemas"]["MessagePart"][];
      request_id?: string | null;
      role: string;
      selected_tools?: string[];
      timestamp?: number | null;
      variants?: components["schemas"]["ChatMessageVariant"][];
      [key: string]: unknown;
    };
    ChatMessageVariant: {
      chat_references?: components["schemas"]["ChatReference"][];
      composer_content?: string;
      delivery_status?: "complete" | "interrupted" | null;
      id: string;
      model_id?: string;
      parts: components["schemas"]["MessagePart"][];
      request_id?: string | null;
      role: string;
      selected_tools?: string[];
      timestamp?: number | null;
      variant_id?: string;
      [key: string]: unknown;
    };
    ChatModelPreference: {
      model: string;
      serviceTier?: "standard" | "fast" | "ultrafast";
      thinkingLevel?: components["schemas"]["ModelReasoningLevel"];
    };
    ChatModelSelectionView: {
      lastUsed: components["schemas"]["ChatModelPreference"] | null;
      next: components["schemas"]["ChatModelPreference"] | null;
    };
    ChatOperationRequest: {
      assistant_message_id: string;
      cancel_token?: string;
      chat_references?: string[] | string;
      composer_content?: string;
      history?: components["schemas"]["ChatMessage"][];
      message?: string;
      model?: string;
      operation?: "send" | "regenerate" | "edit";
      request_id: string;
      selected_tools?: string[] | string;
      serviceTier?: "standard" | "fast" | "ultrafast";
      session_id: string;
      target_message_id?: string | null;
      temporary_chat?: boolean;
      thinkingLevel?: "none" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max" | "ultra";
      user_message_id?: string | null;
      workspace_id?: string;
      [key: string]: unknown;
    };
    ChatOperationResponse: {
      context_usage?: components["schemas"]["ContextUsage"];
      delivery_status?: "complete" | "interrupted";
      history: components["schemas"]["ChatMessage"][];
      ok: boolean;
      reply?: string;
      request_id: string;
      sessionId: string;
      [key: string]: unknown;
    };
    ChatReference: {
      session_id: string;
      title: string;
      workspace_name?: string | null;
    };
    ChatReferenceCandidates: {
      chats: components["schemas"]["ChatReference"][];
    };
    CodexStatus: {
      configured: boolean;
      connected: boolean;
      email?: string | null;
      limits: ({
        name?: string | null;
        primary?: components["schemas"]["CodexUsageWindow"] | null;
        secondary?: components["schemas"]["CodexUsageWindow"] | null;
      })[];
      loginState?: "pending" | "failed" | "idle";
      plan?: string | null;
    };
    CodexUsageWindow: {
      resetsAt?: number | null;
      usedPercent: number;
      windowDurationMins?: number | null;
    };
    ComposerToolEntry: {
      available: boolean;
      descriptionKey: string;
      id: string;
      titleKey: string;
      unavailableKey?: string;
    };
    ContextUsage: {
      context_limit: number;
      estimated_breakdown: boolean;
      input_tokens: number;
      message_tokens: number;
      system_tokens: number;
      tool_tokens: number;
    };
    ErrorResponse: {
      error: {
        code?: string | null;
        message: string;
        [key: string]: unknown;
      };
      ok: boolean;
      request_id?: string | null;
    };
    GuestChatImportRequest: {
      history: components["schemas"]["ChatMessage"][];
      mind_id?: string | null;
      session_id: string;
    };
    GuestChatImportResponse: components["schemas"]["SessionHistoryResponse"] | {
      created: boolean;
    };
    HealthResponse: {
      checks?: Record<string, unknown>;
      latency_ms: number;
      ok: boolean;
      status: "ok" | "degraded" | "fail";
      timestamp: string;
      uptime_seconds: number;
      [key: string]: unknown;
    };
    MessageFileRef: {
      mime_type?: string;
      original_name?: string | null;
      url_path: string;
      [key: string]: unknown;
    };
    MessagePart: components["schemas"]["MessageTextPart"] | {
      image: components["schemas"]["MessageFileRef"];
      [key: string]: unknown;
    } | {
      file: components["schemas"]["MessageFileRef"];
      [key: string]: unknown;
    };
    MessageTextPart: {
      text: string;
      [key: string]: unknown;
    };
    Mind: {
      allow_external_use?: boolean;
      can_edit: boolean;
      category: string;
      created_at?: string | null;
      custom_skill_names?: string[];
      custom_skills?: {
        instructions: string;
        name: string;
      }[];
      description: string;
      id: number;
      instructions?: string;
      is_owner: boolean;
      is_pinned: boolean;
      is_system: boolean;
      is_verified: boolean;
      name: string;
      public_id: string;
      skill_ids?: string[] | null;
      starters: string[];
      updated_at?: string | null;
      visibility: "private" | "link" | "store";
      [key: string]: unknown;
    };
    ModelCatalogEntry: {
      availableUntil?: string;
      contextWindow?: number;
      defaultThinkingLevel?: "none" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max" | "ultra";
      id: string;
      inputModalities?: ("text" | "image")[];
      maxTokens?: number;
      provider?: string;
      serviceTiers?: string[];
      source?: string;
      stage: "release" | "beta" | "dev" | "alpha";
      subtitle: string;
      subtitleKey?: string;
      thinkingLevels?: ("none" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max" | "ultra")[];
      title: string;
      titleKey?: string;
    };
    ModelCatalogResponse: {
      models: components["schemas"]["ModelCatalogEntry"][];
      tools: components["schemas"]["ComposerToolEntry"][];
    };
    ModelReasoningLevel: "none" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max" | "ultra";
    PasswordResetCompleteRequest: {
      code: string;
      password: string;
      reset_request_id: string;
    };
    PasswordResetCompleteResponse: {
      message: "password_reset_complete";
    };
    PasswordResetRequest: {
      email: string;
      language?: string;
    };
    PasswordResetRequestResponse: {
      expires_in: number;
      message: "password_reset_code_sent";
      reset_request_id: string;
    };
    PrivacyDeleteRequest: {
      delete_account?: boolean;
    };
    PrivacyDeleteResponse: {
      deleted: {
        account_deleted?: boolean;
        deleted_at?: string;
        items_deleted?: Record<string, number>;
        user_id?: number;
        [key: string]: unknown;
      };
      ok: boolean;
      request_id?: string | null;
    };
    PrivacyExportPayload: {
      chats?: Record<string, unknown>[];
      exported_at?: string;
      profile?: Record<string, unknown>;
      settings?: Record<string, unknown>;
      shares?: Record<string, unknown>[];
      user_id?: number;
      [key: string]: unknown;
    };
    PrivacyExportResponse: {
      data: components["schemas"]["PrivacyExportPayload"];
      ok: boolean;
      request_id?: string | null;
    };
    ProviderRetryPolicy: {
      backoff: {
        initialDelayMs: number;
        jitterRatio: number;
        maxDelayMs: number;
      };
      maxRetries: number;
      mode: "normal" | "always";
      retryableCodes: ("EMPTY_RESPONSE" | "RATE_LIMIT" | "SERVER" | "TIMEOUT" | "TRANSPORT")[];
    };
    SessionHistoryResponse: {
      history: components["schemas"]["ChatMessage"][];
      is_owner?: boolean;
      is_public?: boolean;
      mind?: components["schemas"]["Mind"] | null;
      model_selection?: components["schemas"]["ChatModelSelectionView"];
      ok: boolean;
      project?: {
        id: string;
        name: string;
      } | null;
      public_id?: string | null;
      read_only?: boolean;
      request_id?: string | null;
      session_id: string;
      share_url?: string | null;
      title?: string | null;
      [key: string]: unknown;
    };
    SessionListResponse: {
      has_more: boolean;
      ok: boolean;
      page: number;
      page_size: number;
      request_id?: string | null;
      sessions: components["schemas"]["SessionSummary"][];
      total: number;
    };
    SessionSummary: {
      is_public?: boolean;
      last_message: string;
      last_updated: number;
      mind?: components["schemas"]["Mind"] | null;
      public_id?: string | null;
      session_id: string;
      source?: "web" | "telegram_private" | "telegram_group" | "telegram_guest" | "telegram_inline";
      title: string;
      workspace_id?: string | null;
    };
    SynthesizeRequest: {
      text: string;
    };
    SynthesizeResponse: {
      ok: boolean;
      request_id?: string | null;
      segments: (string | Record<string, unknown>)[];
      [key: string]: unknown;
    };
    TelegramAgentSettings: {
      bot: string | null;
      businessConnected: boolean;
      canReply: boolean;
      linked: boolean;
      mind_id: string | null;
      model: string;
      secretaryMode: "off" | "mentions" | "all";
      serviceTier: string;
      webSearch: boolean;
    };
    TelegramLinkResponse: {
      expires_in: number;
      request_id: string;
      url: string;
    };
    TelegramLinkStatusRequest: {
      request_id: string;
    };
    TelegramLinkStatusResponse: {
      code?: string;
      status: "pending" | "linked" | "expired" | "failed";
      user?: components["schemas"]["User"];
    };
    TelegramLoginRequest: {
      id_token: string;
      mode?: "login" | "link";
    };
    TranslateRequest: {
      target_lang: string;
      text: string;
    };
    TranslateResponse: {
      ok: boolean;
      request_id?: string | null;
      translated_text: string;
      [key: string]: unknown;
    };
    User: {
      auth_methods?: ("apple" | "google" | "password" | "telegram")[];
      created_at?: string | null;
      email: string | null;
      id: number;
      is_confirmed: boolean;
      oauth_provider?: string | null;
      telegram_bot_ready?: boolean;
      username: string;
    };
    WorkspaceArtifactResult: {
      file: {
        created_at: string;
        download_url: string;
        id: string;
        mime_type: string;
        name: string;
        size: number;
      };
    };
    WorkspacePatchView: {
      applied_at: string | null;
      changes: ({
        destination?: string;
        kind: "add" | "update" | "move" | "delete";
        path: string;
        spreadsheet_formulas_escaped?: boolean;
      })[];
      id: string;
      patch: string;
    };
    WorkspaceProjectFile: {
      created_at: string;
      download_url: string;
      id: string;
      mime_type: string;
      name: string;
      size: number;
    };
  };
}

export interface paths {
  "/api/agent/codex": {
    delete: {
      responses: {
        "200": {
          content: {
            "application/json": {
              connected: boolean;
            };
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
    get: {
      parameters: {
        query: {
          refresh?: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["CodexStatus"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
    post: {
      responses: {
        "200": {
          content: {
            "application/json": {
              code: string;
              url: string;
            };
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/agent/codex/cancel": {
    post: {
      responses: {
        "200": {
          content: {
            "application/json": {
              ok?: boolean;
            };
          };
        };
      };
    };
  };
  "/api/agent/providers": {
    get: {
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentProviderConnections"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/agent/providers/{provider}": {
    delete: {
      parameters: {
        path: {
          provider: string;
        };
      };
      requestBody?: {
        content: {
          "application/json": components["schemas"]["AgentProviderWriteCondition"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentProviderConnections"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
    post: {
      parameters: {
        path: {
          provider: string;
        };
      };
      requestBody?: {
        content: {
          "application/json": components["schemas"]["AgentProviderWriteCondition"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentProviderConnections"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
    put: {
      parameters: {
        path: {
          provider: string;
        };
      };
      requestBody: {
        content: {
          "application/json": {
            baseUrl?: string;
            catalogMode?: components["schemas"]["AgentProviderCatalogMode"];
            expectedRevision?: components["schemas"]["AgentProviderRevision"];
            key?: string;
            models?: components["schemas"]["AgentProviderModel"][];
            name?: string;
            protocol?: "openai-completions" | "openai-responses" | "anthropic-messages" | "google-generative-ai";
            retryPolicy?: components["schemas"]["ProviderRetryPolicy"];
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentProviderConnections"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/agent/providers/{provider}/discover": {
    post: {
      parameters: {
        path: {
          provider: string;
        };
      };
      requestBody: {
        content: {
          "application/json": {
            baseUrl?: string;
            expectedRevision?: components["schemas"]["AgentProviderRevision"];
            key?: string;
            name?: string;
            protocol?: string;
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              models: components["schemas"]["AgentProviderModel"][];
              ok: boolean;
            };
          };
        };
        "401": {
        };
        "409": {
        };
      };
    };
  };
  "/api/agent/runtime": {
    get: {
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentRuntimeSettings"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
    put: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["AgentRuntimeSettings"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentRuntimeSettings"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/agent/skills": {
    get: {
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentSkillCatalog"];
          };
        };
        "401": {
        };
        "404": {
        };
      };
    };
    post: {
      requestBody: {
        content: {
          "application/json": {
            document: components["schemas"]["AgentSkillDocument"];
            replace?: boolean;
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentSkillResult"];
          };
        };
        "201": {
          content: {
            "application/json": components["schemas"]["AgentSkillResult"];
          };
        };
        "400": {
        };
        "401": {
        };
        "404": {
        };
        "409": {
        };
      };
    };
  };
  "/api/agent/skills/unpack": {
    post: {
      requestBody: {
        content: {
          "multipart/form-data": {
            package: string;
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              markdown: string;
              resources: Record<string, string>;
            };
          };
        };
        "400": {
        };
        "401": {
        };
        "413": {
        };
      };
    };
  };
  "/api/agent/skills/{skill_id}": {
    delete: {
      parameters: {
        path: {
          skill_id: string;
        };
      };
      responses: {
        "200": {
        };
        "401": {
        };
        "404": {
        };
      };
    };
    get: {
      parameters: {
        path: {
          skill_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentSkillInspectionResult"];
          };
        };
        "401": {
        };
        "404": {
        };
      };
    };
    patch: {
      parameters: {
        path: {
          skill_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": {
            enabled: boolean;
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentSkillResult"];
          };
        };
        "401": {
        };
        "404": {
        };
      };
    };
  };
  "/api/agent/telegram": {
    get: {
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["TelegramAgentSettings"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
    put: {
      requestBody: {
        content: {
          "application/json": {
            mind_id?: string | null;
            model?: string;
            secretaryMode?: "off" | "mentions" | "all";
            serviceTier?: string;
            webSearch?: boolean;
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["TelegramAgentSettings"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/agent/web-research": {
    get: {
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentWebResearchSettings"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
    put: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["AgentWebResearchUpdate"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentWebResearchSettings"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/auth/apple": {
    post: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["AppleLoginRequest"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AuthLoginResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
      };
    };
  };
  "/api/auth/apple/nonce": {
    get: {
      parameters: {
        query: {
          mode?: "login" | "link";
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AppleChallengeResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
      };
    };
  };
  "/api/auth/check": {
    get: {
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AuthCheckResponse"];
          };
        };
      };
    };
  };
  "/api/auth/config": {
    get: {
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AuthConfigResponse"];
          };
        };
      };
    };
  };
  "/api/auth/login": {
    post: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["AuthLoginRequest"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AuthLoginResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
      };
    };
  };
  "/api/auth/password-reset/complete": {
    post: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["PasswordResetCompleteRequest"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PasswordResetCompleteResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
      };
    };
  };
  "/api/auth/password-reset/request": {
    post: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["PasswordResetRequest"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PasswordResetRequestResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
      };
    };
  };
  "/api/auth/telegram": {
    post: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["TelegramLoginRequest"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AuthLoginResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
      };
    };
  };
  "/api/auth/telegram/link": {
    post: {
      responses: {
        "201": {
          content: {
            "application/json": components["schemas"]["TelegramLinkResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
      };
    };
  };
  "/api/auth/telegram/link/status": {
    post: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["TelegramLinkStatusRequest"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["TelegramLinkStatusResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["AuthErrorResponse"];
          };
        };
      };
    };
  };
  "/api/automations": {
    get: {
      responses: {
        "200": {
          content: {
            "application/json": {
              ok: boolean;
              request_id?: string;
              tasks: components["schemas"]["AutomationTask"][];
            };
          };
        };
        "401": {
        };
      };
    };
    post: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["AutomationCreate"];
        };
      };
      responses: {
        "201": {
          content: {
            "application/json": {
              ok: boolean;
              request_id?: string;
              task: components["schemas"]["AutomationTask"];
            };
          };
        };
        "400": {
        };
        "401": {
        };
        "403": {
        };
        "404": {
        };
        "409": {
        };
        "429": {
        };
      };
    };
  };
  "/api/automations/proposals/{proposal_id}": {
    get: {
      parameters: {
        path: {
          proposal_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              ok: boolean;
              proposal: components["schemas"]["AutomationProposal"];
              request_id?: string;
            };
          };
        };
        "401": {
        };
        "404": {
        };
        "410": {
        };
      };
    };
  };
  "/api/automations/proposals/{proposal_id}/apply": {
    post: {
      parameters: {
        path: {
          proposal_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": {
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              ok: boolean;
              request_id?: string;
              result: {
                removed?: boolean;
                run?: components["schemas"]["AutomationRun"];
                task_id?: string;
              };
            };
          };
        };
        "400": {
        };
        "401": {
        };
        "403": {
        };
        "404": {
        };
        "409": {
        };
        "410": {
        };
        "429": {
        };
      };
    };
  };
  "/api/automations/{task_id}": {
    delete: {
      parameters: {
        path: {
          task_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              deleted: boolean;
              ok: boolean;
              request_id?: string;
            };
          };
        };
        "401": {
        };
        "404": {
        };
        "429": {
        };
      };
    };
    patch: {
      parameters: {
        path: {
          task_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["AutomationUpdate"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              ok: boolean;
              request_id?: string;
              task: components["schemas"]["AutomationTask"];
            };
          };
        };
        "400": {
        };
        "401": {
        };
        "403": {
        };
        "404": {
        };
        "429": {
        };
      };
    };
  };
  "/api/automations/{task_id}/runs": {
    get: {
      parameters: {
        path: {
          task_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              ok: boolean;
              request_id?: string;
              runs: components["schemas"]["AutomationRun"][];
            };
          };
        };
        "401": {
        };
        "404": {
        };
      };
    };
    post: {
      parameters: {
        path: {
          task_id: string;
        };
      };
      responses: {
        "202": {
          content: {
            "application/json": {
              ok: boolean;
              request_id?: string;
              run: components["schemas"]["AutomationRun"];
            };
          };
        };
        "401": {
        };
        "404": {
        };
        "409": {
        };
        "429": {
        };
      };
    };
  };
  "/api/chat-references": {
    get: {
      parameters: {
        query: {
          q?: string;
          session_id?: string;
          workspace_id?: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["ChatReferenceCandidates"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/chatgpt": {
    delete: {
      responses: {
        "200": {
          content: {
            "application/json": {
              revoked: boolean;
            };
          };
        };
      };
    };
    get: {
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["ChatGPTAccount"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/chatgpt/connect": {
    post: {
      requestBody?: {
        content: {
          "application/json": {
            different_account?: boolean;
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              url: string;
            };
          };
        };
      };
    };
  };
  "/api/models": {
    get: {
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["ModelCatalogResponse"];
          };
        };
      };
    };
  };
  "/api/plugins": {
    get: {
      responses: {
        "200": {
          content: {
            "application/json": {
              builtins: components["schemas"]["AgentBuiltinPlugin"][];
              custom: components["schemas"]["AgentCustomPlugin"][];
              ok: boolean;
              request_id?: string;
            };
          };
        };
        "401": {
        };
      };
    };
    post: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["AgentPluginManifest"];
        };
      };
      responses: {
        "201": {
          content: {
            "application/json": {
              ok: boolean;
              plugin: components["schemas"]["AgentCustomPlugin"];
              request_id?: string;
            };
          };
        };
        "400": {
        };
        "401": {
        };
        "409": {
        };
        "429": {
        };
      };
    };
  };
  "/api/plugins/builtin/{skill_id}": {
    put: {
      parameters: {
        path: {
          skill_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": {
            enabled: boolean;
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              enabled: boolean;
              ok: boolean;
              request_id?: string;
            };
          };
        };
        "400": {
        };
        "401": {
        };
        "404": {
        };
        "429": {
        };
      };
    };
  };
  "/api/plugins/{plugin_id}": {
    delete: {
      parameters: {
        path: {
          plugin_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              deleted: boolean;
              ok: boolean;
              request_id?: string;
            };
          };
        };
        "401": {
        };
        "404": {
        };
        "429": {
        };
      };
    };
    patch: {
      parameters: {
        path: {
          plugin_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": {
            enabled?: boolean;
            manifest?: components["schemas"]["AgentPluginManifest"];
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              ok: boolean;
              plugin: components["schemas"]["AgentCustomPlugin"];
              request_id?: string;
            };
          };
        };
        "400": {
        };
        "401": {
        };
        "404": {
        };
        "429": {
        };
      };
    };
  };
  "/api/privacy/delete": {
    post: {
      requestBody?: {
        content: {
          "application/json": components["schemas"]["PrivacyDeleteRequest"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PrivacyDeleteResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/privacy/export": {
    get: {
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["PrivacyExportResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/python/execute": {
    post: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["CanvasPythonExecuteRequest"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["CanvasPythonExecuteResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/user/draft": {
    delete: {
      responses: {
        "200": {
          content: {
            "application/json": {
              deleted: boolean;
            };
          };
        };
      };
    };
    get: {
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["ChatDraftResponse"];
          };
        };
      };
    };
    put: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["ChatDraftRequest"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["ChatDraftResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ChatDraftResponse"];
          };
        };
      };
    };
  };
  "/api/workspaces": {
    get: {
      responses: {
        "200": {
        };
        "400": {
        };
        "401": {
        };
        "404": {
        };
      };
    };
    post: {
      requestBody: {
        content: {
          "application/json": {
            name?: string;
          };
        };
      };
      responses: {
        "200": {
        };
        "201": {
        };
        "400": {
        };
        "401": {
        };
        "404": {
        };
      };
    };
  };
  "/api/workspaces/chats/{session_id}": {
    put: {
      parameters: {
        path: {
          session_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": {
            workspace_id?: string | null;
          };
        };
      };
      responses: {
        "200": {
        };
        "400": {
        };
        "401": {
        };
        "404": {
        };
      };
    };
  };
  "/api/workspaces/{workspace_id}": {
    delete: {
      parameters: {
        path: {
          workspace_id: string;
        };
      };
      responses: {
        "200": {
        };
        "400": {
        };
        "401": {
        };
        "404": {
        };
      };
    };
    get: {
      parameters: {
        path: {
          workspace_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              files: components["schemas"]["WorkspaceProjectFile"][];
              id: string;
              instructions: string;
              name: string;
              ok: boolean;
              request_id?: string;
            };
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
    patch: {
      parameters: {
        path: {
          workspace_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": {
            name?: string;
          };
        };
      };
      responses: {
        "200": {
        };
        "400": {
        };
        "401": {
        };
        "404": {
        };
      };
    };
  };
  "/api/workspaces/{workspace_id}/chats": {
    post: {
      parameters: {
        path: {
          workspace_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": {
            title?: string;
          };
        };
      };
      responses: {
        "200": {
        };
        "201": {
        };
        "400": {
        };
        "401": {
        };
        "404": {
        };
      };
    };
  };
  "/api/workspaces/{workspace_id}/files": {
    post: {
      parameters: {
        path: {
          workspace_id: string;
        };
      };
      requestBody: {
        content: {
          "multipart/form-data": {
            files: string[];
          };
        };
      };
      responses: {
        "201": {
          content: {
            "application/json": {
              files: components["schemas"]["WorkspaceProjectFile"][];
              ok: boolean;
              request_id?: string;
            };
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/workspaces/{workspace_id}/files/from-chat": {
    post: {
      parameters: {
        path: {
          workspace_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": {
            artifact_path: string;
            session_id: string;
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["WorkspaceArtifactResult"];
          };
        };
        "201": {
          content: {
            "application/json": components["schemas"]["WorkspaceArtifactResult"];
          };
        };
        "401": {
        };
        "404": {
        };
        "409": {
        };
      };
    };
  };
  "/api/workspaces/{workspace_id}/files/{file_id}": {
    delete: {
      parameters: {
        path: {
          file_id: string;
          workspace_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              deleted: boolean;
              ok: boolean;
              request_id?: string;
            };
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
    get: {
      parameters: {
        path: {
          file_id: string;
          workspace_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/octet-stream": string;
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/workspaces/{workspace_id}/instructions": {
    put: {
      parameters: {
        path: {
          workspace_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": {
            instructions: string;
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              instructions: string;
              ok: boolean;
              request_id?: string;
            };
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/api/workspaces/{workspace_id}/patches/{proposal_id}": {
    get: {
      parameters: {
        path: {
          proposal_id: string;
          workspace_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["WorkspacePatchView"];
          };
        };
        "401": {
        };
        "404": {
        };
        "410": {
        };
      };
    };
  };
  "/api/workspaces/{workspace_id}/patches/{proposal_id}/apply": {
    post: {
      parameters: {
        path: {
          proposal_id: string;
          workspace_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["WorkspacePatchView"];
          };
        };
        "401": {
        };
        "404": {
        };
        "409": {
        };
        "410": {
        };
      };
    };
  };
  "/api/workspaces/{workspace_id}/skills": {
    get: {
      parameters: {
        path: {
          workspace_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentSkillCatalog"];
          };
        };
        "401": {
        };
        "404": {
        };
      };
    };
    post: {
      parameters: {
        path: {
          workspace_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": {
            document: components["schemas"]["AgentSkillDocument"];
            replace?: boolean;
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentSkillResult"];
          };
        };
        "201": {
          content: {
            "application/json": components["schemas"]["AgentSkillResult"];
          };
        };
        "400": {
        };
        "401": {
        };
        "404": {
        };
        "409": {
        };
      };
    };
  };
  "/api/workspaces/{workspace_id}/skills/{skill_id}": {
    delete: {
      parameters: {
        path: {
          skill_id: string;
          workspace_id: string;
        };
      };
      responses: {
        "200": {
        };
        "401": {
        };
        "404": {
        };
      };
    };
    get: {
      parameters: {
        path: {
          skill_id: string;
          workspace_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentSkillInspectionResult"];
          };
        };
        "401": {
        };
        "404": {
        };
      };
    };
    patch: {
      parameters: {
        path: {
          skill_id: string;
          workspace_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": {
            enabled: boolean;
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["AgentSkillResult"];
          };
        };
        "401": {
        };
        "404": {
        };
      };
    };
  };
  "/chat": {
    post: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["ChatOperationRequest"];
          "multipart/form-data": components["schemas"]["ChatOperationRequest"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["ChatOperationResponse"];
            "text/event-stream": string;
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "403": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "409": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/chat/cancel": {
    post: {
      requestBody: {
        content: {
          "application/json": {
            cancel_token: string;
            request_id: string;
            session_id: string;
          };
        };
      };
      responses: {
        "202": {
          content: {
            "application/json": {
              accepted: boolean;
              ok: boolean;
            };
          };
        };
        "400": {
        };
        "403": {
        };
        "429": {
        };
        "503": {
        };
      };
    };
  };
  "/health": {
    get: {
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["HealthResponse"];
          };
        };
        "503": {
          content: {
            "application/json": components["schemas"]["HealthResponse"];
          };
        };
      };
    };
  };
  "/sessions": {
    get: {
      parameters: {
        query: {
          ids?: string;
          page?: number;
          page_size?: number;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["SessionListResponse"];
          };
        };
      };
    };
  };
  "/sessions/import-active-guest": {
    post: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["GuestChatImportRequest"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["GuestChatImportResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "413": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "429": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/sessions/{session_id}/branch": {
    put: {
      parameters: {
        path: {
          session_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": {
            message_id: string;
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["SessionHistoryResponse"];
          };
        };
      };
    };
  };
  "/sessions/{session_id}/canvas": {
    put: {
      parameters: {
        path: {
          session_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["CanvasSaveRequest"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["CanvasSaveResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/sessions/{session_id}/compact": {
    post: {
      parameters: {
        path: {
          session_id: string;
        };
      };
      requestBody?: {
        content: {
          "application/json": {
            model?: string;
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              compacted_messages: number;
              ok: boolean;
            };
          };
        };
        "401": {
        };
        "404": {
        };
        "409": {
        };
        "422": {
        };
        "502": {
        };
      };
    };
  };
  "/sessions/{session_id}/context-checkpoint": {
    get: {
      parameters: {
        path: {
          session_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": {
              checkpoint: components["schemas"]["ChatContextCheckpoint"] | null;
              ok: boolean;
            };
          };
        };
        "401": {
        };
        "404": {
        };
      };
    };
  };
  "/sessions/{session_id}/history": {
    get: {
      parameters: {
        path: {
          session_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["SessionHistoryResponse"];
          };
        };
        "401": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "404": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
        "500": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/sessions/{session_id}/model-selection": {
    get: {
      parameters: {
        path: {
          session_id: string;
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["ChatModelSelectionView"];
          };
        };
        "401": {
        };
        "404": {
        };
      };
    };
    put: {
      parameters: {
        path: {
          session_id: string;
        };
      };
      requestBody: {
        content: {
          "application/json": components["schemas"]["ChatModelPreference"] | {
            expected_user_id?: number;
          };
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["ChatModelSelectionView"];
          };
        };
        "400": {
        };
        "401": {
        };
        "403": {
        };
        "404": {
        };
        "409": {
        };
      };
    };
  };
  "/synthesize": {
    post: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["SynthesizeRequest"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["SynthesizeResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
  "/translate": {
    post: {
      requestBody: {
        content: {
          "application/json": components["schemas"]["TranslateRequest"];
        };
      };
      responses: {
        "200": {
          content: {
            "application/json": components["schemas"]["TranslateResponse"];
          };
        };
        "400": {
          content: {
            "application/json": components["schemas"]["ErrorResponse"];
          };
        };
      };
    };
  };
}
