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

  send(id: string, text: string): Observable<ConversationMessage> {
    return this.http.post<ConversationMessage>(`${this.base}/${id}/messages`, {
      text,
      attachments: [],
    });
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
