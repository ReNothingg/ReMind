import { adminApi } from './api/admin';
import { canvasApi } from './api/canvas';
import { catalogApi } from './api/catalog';
import { chatApi } from './api/chat';
import { githubApi } from './api/github';
import { mediaApi } from './api/media';
import { mindsApi } from './api/minds';
import { privacyApi } from './api/privacy';
import { resourcesApi } from './api/resources';
import { sessionsApi } from './api/sessions';
import { fetchApi } from './api/transport';
import { buildApiUrl } from './http';
export { CHAT_STREAM_IDLE_TIMEOUT_MS, type ChatStreamReader, readChatStreamChunk } from './api/chat';
export { type ApiServiceError, fetchApi, getGuestSessionToken, getGuestSessionTokens, GUEST_SESSION_TOKENS_KEY, type GuestSessionTokenMap, isGenericHttpMessage, toApiServiceError } from './api/transport';
export { type AdminMind, type AdminMindResponse, type AdminMindsResponse, type AdminMindUpdatePayload, type AdminOverview, type AdminPagination, type AdminUser, type AdminUserResponse, type AdminUsersResponse, type AdminUserUpdatePayload } from './api/types/admin';
export { type ComposerToolOption, type ModelListResponse, type ModelOption, type ModelStage, type ThinkingLevel } from './api/types/catalog';
export { type CanvasActionResponse, type CanvasPythonArtifact, type CanvasPythonExecutionResponse, type CanvasSaveResponse, type CanvasTextdoc, type CanvasTextdocComment, type CanvasUpdate, type ChatCallbacks, type ChatStreamResult, type ChatThinkingUpdate, type ChatWidgetUpdate } from './api/types/chat';
export { type AIResponseFeedbackPayload, type GuestChatImportResponse, type LinkMetadataResponse, type ListSessionsOptions, type PrivacyDeleteResponse, type SessionDeleteResponse, type SessionHistoryWithMind, type SessionMindResponse, type SessionRenameResponse, type SessionShareResponse } from './api/types/common';
export { type GitHubAgentActivity, type GitHubAgentPlan, type GitHubAgentTask, type GitHubAgentTaskResponse, type GitHubInstallation, type GitHubPlanFile, type GitHubPlanStep, type GitHubRepositoriesResponse, type GitHubRepository, type GitHubStatus, type GitHubStatusResponse } from './api/types/github';
export { type Mind, type MindCategory, type MindCategoryResponse, type MindDeleteResponse, type MindListResponse, type MindPayload, type MindResponse, type MindVisibility } from './api/types/minds';
export { getCsrfToken } from './http';
export const apiService = {
  baseURL: buildApiUrl(''),
  _fetch: fetchApi,
  ...chatApi,
  ...sessionsApi,
  ...canvasApi,
  ...catalogApi,
  ...mindsApi,
  ...githubApi,
  ...adminApi,
  ...mediaApi,
  ...resourcesApi,
  ...privacyApi,
};
