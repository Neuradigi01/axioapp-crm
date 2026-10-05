import { Injectable, Signal, WritableSignal, inject, signal } from '@angular/core';
import { Observable, map } from 'rxjs';

import { extractApiError } from '@core/services/api-error.util';

import { AiAssistantsApiService } from '../../ai-assistants/ai-assistants-api.service';
import { PipelinesApiService } from '../../pipelines/pipelines-api.service';
import { MobileSelectOption } from '../../shared/forms/mobile-select.component';
import { UsersDirectoryService } from '../../shared/services/users-directory.service';
import { TemplatesApiService } from '../../templates/templates-api.service';
import { ChatbotsApiService } from '../chatbots-api.service';
import { RefSource } from './node-type-registry';

export interface RefOptionsState {
  status: 'idle' | 'loading' | 'ready' | 'error';
  options: MobileSelectOption[];
  error: string | null;
}

const IDLE: RefOptionsState = { status: 'idle', options: [], error: null };

const CHANNEL_GROUP: Record<string, string> = { whatsapp: 'WhatsApp', email: 'Email' };

/**
 * Option lists for the builder's reference pickers (templates, teammates,
 * bots, AI assistants, lead stages) — so node fields offer a searchable
 * dropdown instead of a pasted UUID. One request per source per session;
 * `ensure()` is idempotent, and a failed load can be retried.
 */
@Injectable({ providedIn: 'root' })
export class BotRefOptionsService {
  private readonly templatesApi = inject(TemplatesApiService);
  private readonly usersDir = inject(UsersDirectoryService);
  private readonly chatbotsApi = inject(ChatbotsApiService);
  private readonly assistantsApi = inject(AiAssistantsApiService);
  private readonly pipelinesApi = inject(PipelinesApiService);

  private readonly states: Record<RefSource, WritableSignal<RefOptionsState>> = {
    template: signal(IDLE),
    user: signal(IDLE),
    chatbot: signal(IDLE),
    ai_assistant: signal(IDLE),
    lead_stage: signal(IDLE),
  };

  state(source: RefSource): Signal<RefOptionsState> {
    return this.states[source].asReadonly();
  }

  /** Start loading `source` unless it is already loading / loaded. */
  ensure(source: RefSource): void {
    const st = this.states[source];
    if (st().status === 'loading' || st().status === 'ready') return;
    st.set({ status: 'loading', options: [], error: null });
    this.fetch(source).subscribe({
      next: (options) => st.set({ status: 'ready', options, error: null }),
      error: (err) =>
        st.set({
          status: 'error',
          options: [],
          error: extractApiError(err) ?? 'Could not load options.',
        }),
    });
  }

  private fetch(source: RefSource): Observable<MobileSelectOption[]> {
    switch (source) {
      case 'template':
        return this.templatesApi
          .list({ is_active: true, channel: ['whatsapp', 'email'], limit: 200 })
          .pipe(
            map((resp) =>
              resp.items
                .map((t) => ({
                  value: t.id,
                  label: t.name,
                  group: CHANNEL_GROUP[t.channel] ?? t.channel,
                }))
                .sort((a, b) => a.group.localeCompare(b.group) || a.label.localeCompare(b.label)),
            ),
          );
      case 'user':
        return this.usersDir.list().pipe(
          map((users) =>
            users
              .filter((u) => u.is_active)
              .map((u) => ({ value: u.id, label: u.full_name || u.email }))
              .sort((a, b) => a.label.localeCompare(b.label)),
          ),
        );
      case 'chatbot':
        return this.chatbotsApi.list({ limit: 200, offset: 0 }).pipe(
          map((bots) =>
            bots
              .filter((b) => b.status !== 'archived')
              .map((b) => ({
                value: b.id,
                label: b.status === 'live' ? b.name : `${b.name} (${b.status})`,
              }))
              .sort((a, b) => a.label.localeCompare(b.label)),
          ),
        );
      case 'ai_assistant':
        return this.assistantsApi.list({ limit: 100 }).pipe(
          map((resp) =>
            resp.items
              .filter((a) => a.status !== 'archived')
              .map((a) => ({
                value: a.id,
                label: a.status === 'active' ? a.name : `${a.name} (${a.status})`,
              }))
              .sort((a, b) => a.label.localeCompare(b.label)),
          ),
        );
      case 'lead_stage':
        // `create_lead` stores the stage KEY of the leads pipeline.
        return this.pipelinesApi
          .getByKey('leads')
          .pipe(
            map((p) =>
              [...p.stages]
                .sort((a, b) => a.display_order - b.display_order)
                .map((s) => ({ value: s.key, label: s.name })),
            ),
          );
    }
  }
}
