/**
 * DEPRECATION SHIM — legacy email-templates API.
 *
 * Step 10 of `tasks/template-library` folded the `core/email_templates/`
 * backend into the central `core/templates/` library. The backend
 * endpoint `/api/v1/email/templates/*` no longer exists. This file
 * stays around so the picker + sequence-builder + compose-bar (which
 * import `EmailTemplate` / `EmailTemplateRenderResponse` /
 * `EmailTemplatesApiService` from here) keep working unchanged —
 * the underlying calls now hit `/api/v1/templates/*`.
 *
 * Removed in a follow-up cleanup PR once the consumers migrate to
 * the central `TemplatesApiService` directly.
 *
 * Shape contract preserved:
 *   - `EmailTemplate` keeps `body_html` + `body_text` fields so
 *     existing consumers compile unchanged. `body_html` is mapped
 *     from the central row's `body_text` (the central library
 *     stores one body per template; HTML vs text is the renderer's
 *     concern).
 *   - `EmailTemplateRenderResponse` is unchanged.
 */
import { Injectable, inject } from '@angular/core';
import { Observable, map, switchMap } from 'rxjs';

import {
  PreviewResponse,
  TemplateListResponse,
  TemplateRead,
  TemplatesApiService,
} from '../templates/templates-api.service';


export interface EmailTemplate {
  id: string;
  org_id: string;
  name: string;
  subject: string;
  body_html: string;
  body_text: string;
  variables_used: string[];
  is_active: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
}


export interface EmailTemplateListResponse {
  items: EmailTemplate[];
  total: number;
  page: number;
  size: number;
}


export interface EmailTemplateCreatePayload {
  name: string;
  subject: string;
  body_html: string;
  body_text?: string;
  is_active?: boolean;
}


export interface EmailTemplateUpdatePayload {
  name?: string;
  subject?: string;
  body_html?: string;
  body_text?: string;
  is_active?: boolean;
}


export interface EmailTemplateRenderResponse {
  subject: string;
  body_html: string;
  body_text: string;
  variables_used: string[];
}


export interface VariableRegistryEntry {
  path: string;
  label: string;
  category: string;
  source: 'system' | 'custom';
}


function _adapt(row: TemplateRead): EmailTemplate {
  return {
    id: row.id,
    org_id: row.org_id,
    name: row.name,
    subject: row.subject ?? '',
    body_html: row.body_text,
    body_text: row.body_text,
    variables_used: row.variables ?? [],
    is_active: row.internal_status !== 'archived',
    created_by: row.created_by_user_id ?? '',
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}


@Injectable({ providedIn: 'root' })
export class EmailTemplatesApiService {
  private readonly central = inject(TemplatesApiService);

  list(filters?: {
    q?: string;
    is_active?: boolean;
    page?: number;
    size?: number;
  }): Observable<EmailTemplateListResponse> {
    const page = filters?.page ?? 1;
    const size = filters?.size ?? 50;
    const offset = (page - 1) * size;
    const internal_status =
      filters?.is_active === false ? ('archived' as const) : undefined;
    return this.central
      .list({
        channel: 'email',
        internal_status,
        q: filters?.q,
        limit: size,
        offset,
      })
      .pipe(
        map((resp: TemplateListResponse) => ({
          items: resp.items
            .map(_adapt)
            .filter((t) =>
              filters?.is_active === true ? t.is_active : true,
            ),
          total: resp.total,
          page,
          size,
        })),
      );
  }

  get(templateId: string): Observable<EmailTemplate> {
    return this.central.get(templateId).pipe(map(_adapt));
  }

  create(payload: EmailTemplateCreatePayload): Observable<EmailTemplate> {
    return this.central
      .create({
        name: payload.name,
        channel: 'email',
        body_text: payload.body_html,
        subject: payload.subject,
      })
      .pipe(map(_adapt));
  }

  update(
    templateId: string,
    payload: EmailTemplateUpdatePayload,
  ): Observable<EmailTemplate> {
    return this.central
      .update(templateId, {
        name: payload.name,
        body_text: payload.body_html,
        subject: payload.subject,
      })
      .pipe(map(_adapt));
  }

  delete(templateId: string): Observable<EmailTemplate> {
    return this.central
      .archive(templateId)
      .pipe(
        switchMap(() => this.central.get(templateId)),
        map(_adapt),
      );
  }

  render(
    templateId: string,
    ctx: { contactId: string; leadId?: string },
  ): Observable<EmailTemplateRenderResponse> {
    return this.central
      .preview(templateId, {
        context: { contact: { id: ctx.contactId } },
      })
      .pipe(
        map((p: PreviewResponse) => ({
          subject: p.subject ?? '',
          body_html: p.body,
          body_text: p.body,
          variables_used: [],
        })),
      );
  }

  variables(): Observable<VariableRegistryEntry[]> {
    return this.central.variables('email').pipe(
      map((rows) =>
        rows.map((v) => ({
          path: v.key,
          label: v.label,
          category: v.key.split('.', 1)[0] ?? 'other',
          source: 'system' as const,
        })),
      ),
    );
  }
}
