import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../environments/environment';
import { buildHttpParams } from '../shared/services/query-builder';

export type ConversationChannel =
  | 'whatsapp'
  | 'instagram'
  | 'facebook'
  | 'web'
  | 'sms'
  | 'email';

export type ConversationStatus = 'open' | 'snoozed' | 'closed';

export type MessageDirection = 'in' | 'out';

export interface Conversation {
  id: string;
  org_id: string;
  channel: ConversationChannel;
  external_id: string;
  contact_id: string | null;
  assigned_to_id: string | null;
  status: ConversationStatus;
  ai_handling: boolean;
  last_message_at: string | null;
  unread_count: number;
  created_at: string;
}

export interface ConversationListResponse {
  items: Conversation[];
  total: number;
  page: number;
  size: number;
}

export interface MessageReaction {
  actor: string;
  emoji: string;
  ts: string;
}

export interface ConversationMessage {
  id: string;
  org_id: string;
  conversation_id: string;
  direction: MessageDirection;
  sender_user_id: string | null;
  text: string | null;
  attachments: Array<Record<string, unknown>>;
  /** Outbound interactive envelope (whatsapp-platform-upgrade Step 6).
   *  Mirrors the validated `InteractivePayload` discriminated union the
   *  builder modal emits — the bubble renderer reads it to show button
   *  labels / list rows. */
  interactive_payload: Record<string, unknown> | null;
  /** UUID of the message this one quotes (Step 7). The thread component
   *  resolves the snippet by looking up the target id in the local
   *  thread cache; cross-pagination quotes fall back to "Original
   *  message". */
  reply_to_message_id: string | null;
  /** Reactions applied to THIS message (Step 7). One entry per actor;
   *  inbound reactions list the reactor's phone, outbound ones list
   *  the staff user id. */
  reactions: MessageReaction[];
  /** Step 13 — true when this message is an operator-only internal note
   *  (yellow-styled bubble; never reaches the customer). */
  is_internal: boolean;
  /** Step 13 — UUIDs of staff @-mentioned in the note. Each gets one
   *  in-app notification on insert. */
  mentioned_user_ids: string[];
  channel_message_id: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  read_at: string | null;
  created_at: string;
}

export interface ConversationDetail {
  conversation: Conversation;
  messages: ConversationMessage[];
}

export interface ConversationListQuery {
  channel?: ConversationChannel;
  status?: ConversationStatus;
  assigned_to?: string;
  q?: string;
  page?: number;
  size?: number;
}

export interface ConversationPatch {
  assigned_to_id?: string | null;
  status?: ConversationStatus;
  ai_handling?: boolean;
}

@Injectable({ providedIn: 'root' })
export class ConversationsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/conversations`;

  list(query: ConversationListQuery = {}): Observable<ConversationListResponse> {
    const params = buildHttpParams({
      channel: query.channel,
      status: query.status,
      assigned_to: query.assigned_to,
      q: query.q,
      page: query.page,
      size: query.size,
    });
    return this.http.get<ConversationListResponse>(this.base, { params });
  }

  detail(id: string): Observable<ConversationDetail> {
    return this.http.get<ConversationDetail>(`${this.base}/${id}`);
  }

  send(
    id: string,
    text: string,
    replyToMessageId?: string | null,
  ): Observable<ConversationMessage> {
    const body: Record<string, unknown> = { text, attachments: [] };
    if (replyToMessageId) body['reply_to_message_id'] = replyToMessageId;
    return this.http.post<ConversationMessage>(
      `${this.base}/${id}/messages`,
      body,
    );
  }

  /**
   * Add / replace / remove a reaction on a message
   * (whatsapp-platform-upgrade Step 7). Pass `null` or `''` as
   * `emoji` to remove the caller's existing reaction — matches
   * Meta's Cloud-API "empty reaction removes" pattern. Returns the
   * target message with its updated `reactions` JSONB.
   */
  reactToMessage(
    conversationId: string,
    messageId: string,
    emoji: string | null,
  ): Observable<ConversationMessage> {
    return this.http.post<ConversationMessage>(
      `${this.base}/${conversationId}/messages/${messageId}/reactions`,
      { emoji },
    );
  }

  /**
   * Post an internal-only note on a conversation
   * (whatsapp-platform-upgrade Step 13).
   *
   * Notes never reach the customer — they're operator annotations
   * rendered yellow in the thread. `mentions` is capped at 5
   * server-side; the picker enforces the same cap.
   */
  postNote(
    conversationId: string,
    text: string,
    mentions: string[] = [],
  ): Observable<ConversationMessage> {
    return this.http.post<ConversationMessage>(
      `${this.base}/${conversationId}/notes`,
      { text, mentions },
    );
  }

  /**
   * Outbound interactive message — reply buttons / CTA URL / list
   * (whatsapp-platform-upgrade Step 6). The backend validates the
   * payload against Meta's published limits before shipping.
   */
  sendInteractive(
    id: string,
    interactive: Record<string, unknown>,
  ): Observable<ConversationMessage> {
    return this.http.post<ConversationMessage>(
      `${this.base}/${id}/messages`,
      { text: '', attachments: [], interactive },
    );
  }

  /**
   * Outbound media message for WhatsApp conversations (whatsapp-
   * platform-upgrade Step 5). Single multipart round-trip — the
   * backend uploads the binary to Meta, mints a media_id, and ships
   * it on the conversation. Backend returns friendly 413/415/422
   * detail messages on size/MIME/type mismatches.
   */
  sendMedia(
    id: string,
    file: File,
    type: 'image' | 'video' | 'audio' | 'document',
    caption?: string,
  ): Observable<ConversationMessage> {
    const form = new FormData();
    form.append('file', file, file.name);
    form.append('type', type);
    if (caption) {
      form.append('caption', caption);
    }
    return this.http.post<ConversationMessage>(
      `${this.base}/${id}/messages/media`,
      form,
    );
  }

  patch(id: string, payload: ConversationPatch): Observable<Conversation> {
    return this.http.patch<Conversation>(`${this.base}/${id}`, payload);
  }
}
