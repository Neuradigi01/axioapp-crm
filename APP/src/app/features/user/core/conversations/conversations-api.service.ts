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
  | 'email'
  | 'ai_widget';

export type ConversationStatus = 'open' | 'snoozed' | 'closed';

export type MessageDirection = 'in' | 'out';

export interface ConversationTagRef {
  id: string;
  name: string;
  color: string;
}

export interface ConversationTag {
  id: string;
  name: string;
  color: string;
  created_by_user_id: string | null;
  created_at: string;
  usage_count: number;
}

export type TagColor =
  | 'zinc'
  | 'rose'
  | 'amber'
  | 'yellow'
  | 'lime'
  | 'emerald'
  | 'teal'
  | 'sky'
  | 'blue'
  | 'indigo'
  | 'violet'
  | 'fuchsia';

export const TAG_PALETTE: TagColor[] = [
  'zinc',
  'rose',
  'amber',
  'yellow',
  'lime',
  'emerald',
  'teal',
  'sky',
  'blue',
  'indigo',
  'violet',
  'fuchsia',
];

/**
 * Tailwind class lookup for tag chips. Kept in lockstep with the
 * backend `_TAG_COLORS` set in `conversations/schemas.py` — adding a
 * color to one without the other breaks rendering.
 */
export const TAG_COLOR_CLASSES: Record<TagColor, string> = {
  zinc: 'bg-surface-2 text-default border-subtle',
  rose: 'bg-red-500/10 text-red-400 ring-red-500/20',
  amber: 'bg-amber-100 text-amber-800 ring-amber-200',
  yellow: 'bg-yellow-100 text-yellow-800 ring-yellow-200',
  lime: 'bg-lime-100 text-lime-800 ring-lime-200',
  emerald: 'bg-emerald-100 text-emerald-700 ring-emerald-200',
  teal: 'bg-teal-100 text-teal-700 ring-teal-200',
  sky: 'bg-sky-100 text-sky-700 ring-sky-200',
  blue: 'bg-blue-100 text-blue-700 ring-blue-200',
  indigo: 'bg-indigo-100 text-indigo-700 ring-indigo-200',
  violet: 'bg-violet-100 text-violet-700 ring-violet-200',
  fuchsia: 'bg-fuchsia-100 text-fuchsia-700 ring-fuchsia-200',
};

export interface Conversation {
  id: string;
  org_id: string;
  channel: ConversationChannel;
  external_id: string;
  contact_id: string | null;
  assigned_to_id: string | null;
  status: ConversationStatus;
  ai_handling: boolean;
  /** tasks/ai-assistants-omnichannel Step 3 — human-takeover state.
   *  ``ai_paused=true`` means a human clicked Take Over and the AI is
   *  silent on this thread until Return to AI. First-come-first-serve
   *  via a backend compare-and-set on `POST /conversations/{id}/pause-ai`.
   */
  ai_paused?: boolean;
  ai_paused_by_user_id?: string | null;
  ai_paused_at?: string | null;
  /** Server-computed: true when AI will actually answer the next
   *  inbound on this conversation — i.e. NOT paused AND (per-conv
   *  `ai_handling` flag OR the org has an active assistant bound to
   *  this channel). The chat-thread banner gates on this so the
   *  "🤖 AI is handling" banner never renders when no AI is really
   *  configured for the channel. */
  ai_active?: boolean;
  last_message_at: string | null;
  /** Short preview of the most recent external message (whitespace-collapsed
   *  + trimmed to 140 chars server-side). Populated by the list endpoint
   *  so the inbox row renders a snippet without a per-row fetch; null on
   *  the detail response and when the conversation has no messages / only
   *  attachment-only messages / only internal notes. */
  last_message_body?: string | null;
  unread_count: number;
  created_at: string;
  /** Step 14 — assigned tag chips. Empty array when none / not loaded. */
  tags: ConversationTagRef[];
  /** Step 24 — click-to-WhatsApp ad attribution. Set on the first
   *  inbound that carried a Meta `referral` block; null on organic.
   *  The chat-thread chip + filters read `acquisition_source ==='ad'`
   *  to decide whether to render. */
  acquisition_source?: 'organic' | 'ad' | 'qr' | 'wa_me' | 'form' | null;
  acquisition_campaign_id?: string | null;
  acquisition_ad_id?: string | null;
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
  /** Author display name resolved server-side (from tbl_user_login +
   *  tbl_user_info). Populated for outbound / internal-note messages;
   *  null for inbound customer messages. Prefer this over the client-
   *  side staffById lookup — the server sees inactive/former members
   *  too, avoiding "Unknown user" for historical notes.
   *  Optional so optimistic-render call sites (page composes a local
   *  Message before the round-trip lands the enriched one) can omit
   *  it; the template's `m.sender_display_name || staffNameFor(...)`
   *  fallback handles the undefined case identically to null. */
  sender_display_name?: string | null;
  /** Step 19 — true when this outbound message was generated by the
   *  AI agent. Frontend bubble renders a "🤖 AI" badge. */
  is_ai: boolean;
  channel_message_id: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  read_at: string | null;
  created_at: string;
}

export interface WhatsAppSessionState {
  in_session: boolean;
  expires_at: string | null;
  hours_remaining: number;
  last_customer_message_at: string | null;
}

export interface ConversationDetail {
  conversation: Conversation;
  messages: ConversationMessage[];
  /** Step 15 — only populated for WhatsApp conversations. */
  whatsapp_session_state: WhatsAppSessionState | null;
}

export interface ConversationListQuery {
  channel?: ConversationChannel;
  status?: ConversationStatus;
  assigned_to?: string;
  q?: string;
  /** Step 14 — OR-semantic filter on tag ids. */
  tag_ids?: string[];
  /** Inbox "Unread" chip — restricts the list to threads with
   *  `unread_count > 0`. Composes with the other filters. */
  unread_only?: boolean;
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

  /** Start (or resume) a conversation from the inbox's *New* button.
   *  Resolves the picked contact's phone / email server-side per the
   *  chosen channel; 422 when the contact lacks the required identifier
   *  so the caller can render "add a phone/email first" inline. */
  create(channel: ConversationChannel, contactId: string): Observable<Conversation> {
    return this.http.post<Conversation>(this.base, {
      channel,
      contact_id: contactId,
    });
  }

  list(query: ConversationListQuery = {}): Observable<ConversationListResponse> {
    const params = buildHttpParams({
      channel: query.channel,
      status: query.status,
      assigned_to: query.assigned_to,
      q: query.q,
      tag_ids: query.tag_ids,
      unread_only: query.unread_only ? true : undefined,
      page: query.page,
      size: query.size,
    });
    return this.http.get<ConversationListResponse>(this.base, { params });
  }

  detail(id: string): Observable<ConversationDetail> {
    return this.http.get<ConversationDetail>(`${this.base}/${id}`);
  }

  /**
   * Fetch an older page of messages (infinite-scroll-up). Returns
   * oldest-first so the caller can prepend it to the top of the
   * rendered thread. Empty array means the thread is fully loaded.
   *
   * ``beforeId`` is the id of the current oldest visible message —
   * the backend keyset-walks past it. Backend caps ``limit`` at 200.
   */
  loadOlderMessages(
    conversationId: string,
    beforeId: string,
    limit = 50,
  ): Observable<ConversationMessage[]> {
    return this.http.get<ConversationMessage[]>(`${this.base}/${conversationId}/messages`, {
      params: { before_id: beforeId, limit: String(limit) },
    });
  }

  send(
    id: string,
    text: string,
    replyToMessageId?: string | null,
    sendFromPhoneId?: string | null,
    attachments?: Array<Record<string, unknown>>,
  ): Observable<ConversationMessage> {
    const body: Record<string, unknown> = {
      text,
      attachments: attachments ?? [],
    };
    if (replyToMessageId) body['reply_to_message_id'] = replyToMessageId;
    // Step 27b — multi-number Send-From selection. Server resolves
    // the adapter against this phone instead of the org default.
    // NULL/omitted keeps the legacy behaviour for single-number orgs.
    if (sendFromPhoneId) body['send_from_phone_id'] = sendFromPhoneId;
    return this.http.post<ConversationMessage>(`${this.base}/${id}/messages`, body);
  }

  /** Send an approved WhatsApp template through an existing
   *  conversation. Powers the inbox composer's inline template picker
   *  when the 24-hour session window has expired — Meta only accepts
   *  approved templates outside the window.
   *
   *  ``variables`` maps `{{n}}` placeholder index (1-based, as a
   *  string) to the resolved value. Empty when the template has no
   *  variables. */
  sendTemplate(
    id: string,
    payload: {
      templateId: string;
      variables?: Record<string, string>;
      sendFromPhoneId?: string | null;
    },
  ): Observable<ConversationMessage> {
    const body: Record<string, unknown> = {
      template_id: payload.templateId,
      variables: payload.variables ?? {},
    };
    if (payload.sendFromPhoneId) body['send_from_phone_id'] = payload.sendFromPhoneId;
    return this.http.post<ConversationMessage>(`${this.base}/${id}/messages/template`, body);
  }

  /** Reply to an email conversation from the unified inbox. Routes to
   *  the typed email endpoint (the generic `/messages` guard rejects
   *  email because it needs subject + sender-account). Body-only send
   *  works — the backend auto-derives subject (`Re: (no subject)`),
   *  picks the sender's first live connected mailbox, and threads the
   *  reply to the newest inbound message. */
  sendEmailReply(
    id: string,
    body: { bodyText: string; bodyHtml?: string; subject?: string; accountId?: string },
  ): Observable<ConversationMessage> {
    const payload: Record<string, unknown> = { body_text: body.bodyText };
    if (body.bodyHtml) payload['body_html'] = body.bodyHtml;
    if (body.subject) payload['subject'] = body.subject;
    if (body.accountId) payload['account_id'] = body.accountId;
    return this.http.post<ConversationMessage>(`${this.base}/${id}/email-reply`, payload);
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
   * Zero the unread badge on a conversation. Idempotent — safe to
   * fire on every thread open even if the counter is already 0. The
   * SPA calls this from the thread-open effect + the list row's
   * "Mark as read" context-menu item.
   */
  markRead(conversationId: string): Observable<Conversation> {
    return this.http.post<Conversation>(`${this.base}/${conversationId}/mark-read`, {});
  }

  /**
   * Flip a conversation back to unread by setting ``unread_count = 1``
   * if it's currently 0. Powers the "come back to this later" row
   * action.
   */
  markUnread(conversationId: string): Observable<Conversation> {
    return this.http.post<Conversation>(`${this.base}/${conversationId}/mark-unread`, {});
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
    return this.http.post<ConversationMessage>(`${this.base}/${conversationId}/notes`, {
      text,
      mentions,
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
    return this.http.post<ConversationMessage>(`${this.base}/${id}/messages`, {
      text: '',
      attachments: [],
      interactive,
    });
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
    return this.http.post<ConversationMessage>(`${this.base}/${id}/messages/media`, form);
  }

  patch(id: string, payload: ConversationPatch): Observable<Conversation> {
    return this.http.patch<Conversation>(`${this.base}/${id}`, payload);
  }

  // --- AI takeover (omnichannel Step 4) ------------------------------

  /** Human takes over — pause AI on this conversation.
   *  409 ``already_taken_over`` on race (loser gets holder details in
   *  the body); 200 with the updated Conversation on win. */
  pauseAi(id: string): Observable<Conversation> {
    return this.http.post<Conversation>(`${this.base}/${id}/pause-ai`, {});
  }

  /** Return this conversation to AI. Holder-or-admin only server-side;
   *  403 ``not_holder`` when a non-holder without
   *  ``settings.conversations.manage`` calls it. */
  resumeAi(id: string): Observable<Conversation> {
    return this.http.post<Conversation>(`${this.base}/${id}/resume-ai`, {});
  }

  // --- Tags (whatsapp-platform-upgrade Step 14) -----------------------

  /** List every tag in the active org with its assignment count. */
  listTags(search?: string): Observable<ConversationTag[]> {
    const params = buildHttpParams({ search });
    return this.http.get<ConversationTag[]>(`${this.base}/tags`, { params });
  }

  /** Create a new tag. Server enforces case-insensitive uniqueness;
   *  409 on duplicate. */
  createTag(name: string, color: TagColor): Observable<ConversationTag> {
    return this.http.post<ConversationTag>(`${this.base}/tags`, {
      name,
      color,
    });
  }

  /** Rename / recolor an existing tag. Both fields optional. */
  updateTag(
    tagId: string,
    patch: { name?: string; color?: TagColor },
  ): Observable<ConversationTag> {
    return this.http.patch<ConversationTag>(`${this.base}/tags/${tagId}`, patch);
  }

  /** Delete a tag. Cascade-removes every assignment. */
  deleteTag(tagId: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/tags/${tagId}`);
  }

  /** Attach a tag to a conversation. Idempotent. Returns the updated
   *  tag list so the SPA can swap chips without a follow-up fetch. */
  assignTag(conversationId: string, tagId: string): Observable<ConversationTagRef[]> {
    return this.http.post<ConversationTagRef[]>(`${this.base}/${conversationId}/tags`, {
      tag_id: tagId,
    });
  }

  /** Detach a tag from a conversation. Idempotent. */
  unassignTag(conversationId: string, tagId: string): Observable<ConversationTagRef[]> {
    return this.http.delete<ConversationTagRef[]>(`${this.base}/${conversationId}/tags/${tagId}`);
  }
}
