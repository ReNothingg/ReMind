import {
type SessionHistoryResponse
} from "../../openapiClient";
import { Mind } from './minds';

export type ListSessionsOptions =
    | string
    | {
          idsQuery?: string;
          page?: number;
          pageSize?: number;
      };

export type SessionShareResponse = {
    is_owner?: boolean;
    is_public?: boolean;
    public_id?: string | null;
    read_only?: boolean;
    session_id?: string;
    share_url?: string | null;
    [key: string]: unknown;
};

export type SessionRenameResponse = {
    title?: string;
    [key: string]: unknown;
};

export type GuestChatImportResponse = SessionHistoryWithMind & {
    created?: boolean;
};

export type SessionHistoryWithMind = SessionHistoryResponse & {
    mind?: Mind | null;
};

export type SessionMindResponse = {
    mind?: Mind | null;
    session_id?: string;
};

export type AIResponseFeedbackPayload = {
    session_id: string;
    message_client_id?: string;
    rating: 'like' | 'dislike';
    reason_codes?: string[];
    comment?: string;
    response_text: string;
};

export type LinkMetadataResponse = Record<string, unknown>;

export type PrivacyDeleteResponse = Record<string, unknown>;

export type SessionDeleteResponse = Record<string, unknown>;
