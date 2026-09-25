import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { environment } from '../../../../../environments/environment';
import { FieldDef } from '../shared/dynamic-form/types';
import { FilterDsl, isEmptyFilter } from '../shared/filter-dsl.types';
import { BaseCrudApiService } from '../shared/services/base-crud-api.service';
import {
  buildHttpParams,
  prefixCustomFilters,
  stripPaginationKeys,
} from '../shared/services/query-builder';

export type LeadStatus = 'active' | 'won' | 'lost';

/** Provenance of a lead row. Matches the backend `lead_source` PG enum
 * exactly — keep in sync. */
export type LeadSource =
  | 'manual'
  | 'bulk_import'
  | 'widget'
  | 'google_ads'
  | 'meta_ads'
  | 'whatsapp_flow'
  | 'walk_in';

export interface Lead {
  id: string;
  org_id: string;
  contact_id: string;
  pipeline_stage: string;
  status: LeadStatus;
  source: LeadSource;
  assigned_to_id: string | null;
  budget: string | null;
  /** ISO-4217 code. Null → renderers fall back to the org's default
   *  currency (from `/users/me → org.currency`). */
  currency: string | null;
  expected_close_date: string | null;
  /** Operator-defined rule engine output, clamped `[0, 100]`. Surfaced
   * for the Step 6 "Score" column. */
  lead_score: number;
  custom_data: Record<string, unknown>;
  last_activity_at: string | null;
  lost_reason: string | null;
  lost_reason_other: string | null;
  /** Won-capture fields (F2). Set by the move-stage endpoint when the
   *  destination stage has `is_won=true`. */
  won_value: string | null;
  close_date: string | null;
  won_reason: string | null;
  /** Lifecycle timestamps (F22). Auto-stamped by move-stage on first
   *  entry into an `is_won` / `is_lost` stage. Feed the funnel
   *  time-in-stage story once the reports UI lands. */
  won_at: string | null;
  lost_at: string | null;
  /** Origin-channel attribution metadata. Populated by the ingest layer
   * for `widget`, `google_ads`, `meta_ads` sources; null for `manual`
   * and `bulk_import`. Keys vary by channel — Google Ads sends
   * `external_form_id`, `external_lead_id`, `campaign_id`, `gclid`;
   * Meta sends `external_form_id`, `external_lead_id`, `page_id`;
   * widget sends `utm_source`, `utm_medium`, `utm_campaign`, `referrer`. */
  attribution: Record<string, unknown> | null;
  /** W6 attribution — set when the lead was created from a walk-in
   *  conversion. Detail-page renders an "Originated from walk-in"
   *  panel that deep-links back to the walk-in row when set. */
  source_walk_in_id?: string | null;
  created_at: string;
  updated_at: string;
  /** Index signature so `Lead` is structurally compatible with `PipelineItem`. */
  [key: string]: unknown;
}

export type LeadSortKey =
  | 'created_at'
  | 'last_activity_at'
  | 'lead_score'
  | 'contact_name'
  | 'next_follow_up_due';
export type SortOrder = 'asc' | 'desc';

/**
 * Paged list response.
 *
 * `total` is `null` when the caller passed `with_total=false` (the
 * backend skips the COUNT(*) in that case for keyset performance).
 * `next_cursor` is `null` when the set is exhausted.
 */
export interface LeadListResponse {
  items: Lead[];
  total: number | null;
  /** Tenant-wide count ignoring every filter. Non-null only when the
   * caller passes `with_unfiltered_total=true`. Used by the Leads
   * Center header to render `(filtered/total)`. */
  unfiltered_total: number | null;
  page: number;
  size: number;
  next_cursor: string | null;
}

export interface LeadCreate {
  contact_id: string;
  pipeline_stage?: string | null;
  assigned_to_id?: string | null;
  budget?: string | null;
  currency?: string | null;
  expected_close_date?: string | null;
  custom_data?: Record<string, unknown>;
  /** Defaults to 'manual' server-side when omitted. */
  source?: LeadSource;
}

/** Response body returned by ``POST /leads``.
 *
 *  Every field on :class:`Lead` plus ``ingest_action`` — the ingest
 *  layer's discriminator so the UI can show a contextual toast:
 *
 *  - ``"created"`` — a fresh lead row was inserted.
 *  - ``"merged"`` — the picked contact already had an OPEN lead; its
 *    timeline gained a "Touchpoint via <source>" activity and this
 *    response carries that existing lead's fields.
 */
export interface LeadIngestResult extends Lead {
  ingest_action: 'created' | 'merged';
}

export type LeadUpdate = Partial<{
  contact_id: string;
  assigned_to_id: string | null;
  source: LeadSource | null;
  budget: string | null;
  currency: string | null;
  expected_close_date: string | null;
  custom_data: Record<string, unknown>;
  lost_reason: string | null;
  lost_reason_other: string | null;
  won_value: string | null;
  close_date: string | null;
  won_reason: string | null;
}>;

/** Narrow contact-basics patch surface exposed by the log-update
 * endpoint. Backend rejects any extra field (Pydantic
 * ``extra=forbid``), so the type stays strictly to the three fields
 * sir's screenshot exposes. */
export interface FollowUpContactBasics {
  full_name?: string;
  phone?: string;
  email?: string;
}

/** Follow-up task payload written to ``tbl_tasks`` when the modal
 * schedules a next-touch. Persists as an open task with
 * ``related_entity_type='lead'`` so the dashboard's Today's Follow-ups
 * widget picks it up unchanged. */
export interface NextFollowUpSpec {
  due_at: string;
  followup_type: 'call' | 'whatsapp' | 'email' | 'document' | 'meeting' | 'other';
}

/** Payload for ``POST /leads/{id}/log-update``. Mirrors the backend
 * ``LogUpdateRequest`` shape one-for-one. ``if_current_stage`` is the
 * optimistic-lock guard captured when the modal opened. */
export interface LogUpdateRequest {
  if_current_stage: string;
  contact_basics?: FollowUpContactBasics | null;
  pipeline_stage?: string | null;
  source?: LeadSource | null;
  remarks: string;
  next_follow_up?: NextFollowUpSpec | null;
  /** Owner change — supply BOTH `set_assigned_to=true` AND the target
   *  `assigned_to_id` (nullable, `null` clears the owner). Omit the
   *  sentinel to leave owner untouched. Backend writes a `reassign`
   *  activity in the same atomic transaction. Requires
   *  `leads.reassign`. */
  assigned_to_id?: string | null;
  set_assigned_to?: boolean;
  lost_reason?: string | null;
  lost_reason_other?: string | null;
}

/** Response body from ``POST /leads/{id}/log-update``. Carries the
 * refreshed lead + the created task id (or null when the payload had
 * no ``next_follow_up`` block). */
export interface LogUpdateResponse {
  lead: Lead;
  next_follow_up_task_id: string | null;
}

/** Header-strip roll-up rendered above the kanban / list view (F23).
 *  Values are strings because Pydantic serialises Decimal as a string
 *  by default; the frontend formats via `Intl.NumberFormat` using the
 *  returned `currency`. */
export interface PipelineValueByCurrency {
  currency: string;
  open_value: string;
  won_value_this_month: string;
}

export interface PipelineValueRollup {
  open_value: string;
  open_count: number;
  won_value_this_month: string;
  won_count_this_month: number;
  lost_count_this_month: number;
  currency: string;
  /** Per-currency split for mixed-currency orgs. Empty when every
   *  lead uses the org default (flat totals are authoritative). */
  by_currency?: PipelineValueByCurrency[];
}

/** Routing config (F1 / E.16). v1 accepts only `round_robin`; the
 *  Literal widens here + on the backend when `sticky_by_source` or
 *  future strategies actually land. */
export type LeadRoutingStrategy = 'round_robin';

export interface LeadRoutingConfig {
  strategy: LeadRoutingStrategy;
}

// --- Lead scoring rules (Step 7 admin UI) ---------------------------------

/** A single scoring rule. `condition` is the same shape as the leads
 * filter DSL (an `all`/`any` group of clauses) — the backend's scoring
 * engine evaluates it against each lead row at write time and on
 * recompute. Points are bounded `[-100, 100]`; the engine clamps the
 * final score to `[0, 100]` after summing active matches. */
export interface LeadScoringRule {
  id: string;
  org_id: string;
  name: string;
  condition: FilterDsl;
  points: number;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface LeadScoringRuleCreate {
  name: string;
  condition: FilterDsl;
  points: number;
  active?: boolean;
}

export type LeadScoringRuleUpdate = Partial<{
  name: string;
  condition: FilterDsl;
  points: number;
  active: boolean;
}>;

export interface LeadListQuery {
  stage?: string;
  status?: LeadStatus;
  assigned_to?: string | null;
  /** When true, only leads with `assigned_to_id IS NULL` are returned.
   *  Ignored if `assigned_to` is also set. Powers the "Unassigned"
   *  chip on the assignee filter. */
  unassigned_only?: boolean;
  q?: string;
  source?: string;
  /** ISO timestamps for the no-activity chip. `lt` returns rows older
   * than the cutoff OR with a NULL `last_activity_at` — the backend
   * treats never-touched leads as "very old" so they surface in the
   * "no activity > N days" filter. */
  last_activity_lt?: string;
  last_activity_gt?: string;
  /** Inclusive date range on ``created_at`` (Step 2 backend surface).
   * Accepts a YYYY-MM-DD string; the backend UTC-anchors both bounds. */
  created_from?: string;
  created_to?: string;
  /** Case-insensitive substring match against any `note` activity on
   * the lead. Capped at 64 chars server-side. */
  remarks_contains?: string;
  sort?: LeadSortKey;
  order?: SortOrder;
  /** Offset mode (legacy). When `cursor` is set, page is ignored. */
  page?: number;
  /** Offset-mode page size. Defaults to 50 server-side. */
  size?: number;
  /** Cursor-mode token (opaque base64 from the previous response's
   * `next_cursor`). Pass `null`/omit for the first page. */
  cursor?: string | null;
  /** Cursor-mode limit. Clamped server-side to `[1, 200]`. */
  limit?: number;
  /** Skip the COUNT(*). The list page passes `true` on first page so
   * the footer can show "X of N"; subsequent pages pass `false`. */
  with_total?: boolean;
  /** Opt-in for the tenant-wide unfiltered count. Cheap extra COUNT(*)
   * behind the ORM's tenant filter — only worth requesting when the
   * response consumer is rendering `(filtered/total)`. */
  with_unfiltered_total?: boolean;
  customFilters?: Record<string, string>;
  /** Advanced filter DSL (see `shared/filter-dsl.types`). Service
   * JSON-stringifies it into the `filter` query param. */
  filter?: FilterDsl | null;
}

@Injectable({ providedIn: 'root' })
export class LeadsApiService extends BaseCrudApiService<Lead, LeadCreate, LeadUpdate> {
  protected readonly base = `${environment.apiBaseUrl}/leads`;
  private readonly renderUrl = `${environment.apiBaseUrl}/custom-fields/lead/render`;

  list(query: LeadListQuery = {}): Observable<LeadListResponse> {
    return this.http.get<LeadListResponse>(this.base, {
      params: this.buildParams(query),
    });
  }

  /** Override the base ``create`` so the response body carries
   *  ``ingest_action`` — the discriminator the UI reads to show
   *  "New lead created" vs "Existing lead updated". Backend also
   *  still sets an ``X-Lead-Ingest-Action`` header for legacy
   *  clients; new consumers read the body. */
  override create(payload: LeadCreate): Observable<LeadIngestResult> {
    return this.http.post<LeadIngestResult>(this.base, payload);
  }

  /** Trigger a CSV download for the current filter set. Uses the auth
   * interceptor to attach the bearer token (the browser can't pass
   * `Authorization` headers via a plain `<a download>`), fetches the
   * stream as a blob, then synthesises a download click on a hidden
   * anchor. `query.page`, `size`, `cursor`, and `limit` are dropped —
   * the CSV endpoint always returns the full filtered set up to the
   * server cap. */
  exportCsv(query: LeadListQuery = {}): Observable<Blob> {
    return this.http.get(`${this.base}/export.csv`, {
      params: this.buildParams(stripPaginationKeys(query)),
      responseType: 'blob',
    });
  }

  /** Stream a blob to the user as a file download. Handles URL
   * lifecycle (revoke after the click so the GC can reclaim the blob).
   * Filename falls back to "leads.csv" if the caller passes nothing. */
  triggerDownload(blob: Blob, filename = 'leads.csv'): void {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    // Slight delay so the browser has a chance to start the download
    // before the URL becomes invalid. 0ms via setTimeout puts it after
    // the current microtask, which is enough.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  moveStage(
    id: string,
    toStage: string,
    extras?: {
      lost_reason?: string | null;
      lost_reason_other?: string | null;
      /** F2 — Won capture. Optional on the API; the frontend modal
       *  prompts and enforces. */
      won_value?: string | null;
      close_date?: string | null;
      won_reason?: string | null;
    },
  ): Observable<Lead> {
    return this.http.post<Lead>(`${this.base}/${id}/move-stage`, {
      to_stage: toStage,
      lost_reason: extras?.lost_reason ?? null,
      lost_reason_other: extras?.lost_reason_other ?? null,
      won_value: extras?.won_value ?? null,
      close_date: extras?.close_date ?? null,
      won_reason: extras?.won_reason ?? null,
    });
  }

  /** Update-Status modal write path. Atomic on the backend: contact
   *  patch + stage move + source change + note activity + follow-up
   *  task all commit together or roll back together. See
   *  ``tasks/leads-update-status-flow/step-1-backend-log-update-endpoint.md``
   *  for the contract; the modal that calls this lives in
   *  ``update-status-modal.component.ts``. */
  logUpdate(id: string, payload: LogUpdateRequest): Observable<LogUpdateResponse> {
    return this.http.post<LogUpdateResponse>(`${this.base}/${id}/log-update`, payload);
  }

  /** F4 — Bulk move-stage. Moves every id to the same `to_stage`;
   *  same validation rules as single-row move-stage apply (Lost
   *  needs a reason). Returns `{moved, already_in_stage}` so the FE
   *  can render an honest "X moved, Y already there" summary
   *  (previous shape underreported by rolling both into `reassigned`). */
  bulkMoveStage(
    ids: string[],
    toStage: string,
    extras?: {
      lost_reason?: string | null;
      lost_reason_other?: string | null;
      won_value?: string | null;
      close_date?: string | null;
      won_reason?: string | null;
    },
  ): Observable<{ moved: number; already_in_stage: number }> {
    return this.http.post<{ moved: number; already_in_stage: number }>(
      `${this.base}/bulk-move-stage`,
      {
        ids,
        to_stage: toStage,
        lost_reason: extras?.lost_reason ?? null,
        lost_reason_other: extras?.lost_reason_other ?? null,
        won_value: extras?.won_value ?? null,
        close_date: extras?.close_date ?? null,
        won_reason: extras?.won_reason ?? null,
      },
    );
  }

  /** F23 — Pipeline value roll-up. Scope follows caller's row
   *  visibility (org vs. personal) — decided server-side. */
  pipelineValue(): Observable<PipelineValueRollup> {
    return this.http.get<PipelineValueRollup>(`${this.base}/pipeline-value`);
  }

  /** Single-row reassign. `userId === null` clears the owner. */
  reassign(id: string, body: { userId: string | null; note?: string | null }): Observable<Lead> {
    return this.http.post<Lead>(`${this.base}/${id}/reassign`, {
      assigned_to_id: body.userId,
      note: body.note ?? null,
    });
  }

  bulkReassign(
    ids: string[],
    body: { userId: string | null; note?: string | null },
  ): Observable<{ reassigned: number }> {
    return this.http.post<{ reassigned: number }>(`${this.base}/bulk-reassign`, {
      ids,
      assigned_to_id: body.userId,
      note: body.note ?? null,
    });
  }

  bulkDelete(ids: string[]): Observable<{ deleted: number }> {
    return this.http.post<{ deleted: number }>(`${this.base}/bulk-delete`, {
      ids,
    });
  }

  /** Field defs for `entity_type='lead'` — feeds the dynamic form. */
  renderFields(): Observable<FieldDef[]> {
    return this.http.get<FieldDef[]>(this.renderUrl);
  }

  /** Manual create that surfaces the ingest action alongside the
   *  lead. ``action='merged'`` means the picked contact already had
   *  an open lead — no new row was inserted and the returned lead is
   *  the pre-existing one with a touchpoint activity appended. The
   *  UI uses this to switch its success toast from "New lead
   *  created" to "Existing lead updated with a new touchpoint".
   *
   *  Reads ``ingest_action`` from the response body (backend Fix I.2).
   *  The prior ``X-Lead-Ingest-Action`` header path is still populated
   *  by the backend for legacy clients but the body is safer: any
   *  CORS-transparent proxy or middleware that strips response headers
   *  used to silently regress this to "created". */
  createWithAction(payload: LeadCreate): Observable<{ lead: Lead; action: 'created' | 'merged' }> {
    return this.http.post<LeadIngestResult>(this.base, payload).pipe(
      map((body) => {
        const action: 'created' | 'merged' = body.ingest_action === 'merged' ? 'merged' : 'created';
        const { ingest_action: _drop, ...lead } = body;
        void _drop;
        return { lead: lead as Lead, action };
      }),
    );
  }

  // --- Lead scoring rules (Step 7 admin UI) ------------------------------

  listScoringRules(): Observable<LeadScoringRule[]> {
    return this.http.get<LeadScoringRule[]>(`${this.base}/scoring-rules`);
  }

  createScoringRule(payload: LeadScoringRuleCreate): Observable<LeadScoringRule> {
    return this.http.post<LeadScoringRule>(`${this.base}/scoring-rules`, payload);
  }

  updateScoringRule(id: string, payload: LeadScoringRuleUpdate): Observable<LeadScoringRule> {
    return this.http.patch<LeadScoringRule>(`${this.base}/scoring-rules/${id}`, payload);
  }

  deleteScoringRule(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/scoring-rules/${id}`);
  }

  recomputeScores(): Observable<{ touched: number }> {
    return this.http.post<{ touched: number }>(`${this.base}/scoring-rules/recompute`, {});
  }

  // --- Routing config (F1 / E.16) -----------------------------------------

  getRoutingConfig(): Observable<LeadRoutingConfig> {
    return this.http.get<LeadRoutingConfig>(`${this.base}/routing-config`);
  }

  updateRoutingConfig(payload: LeadRoutingConfig): Observable<LeadRoutingConfig> {
    return this.http.put<LeadRoutingConfig>(`${this.base}/routing-config`, payload);
  }

  private buildParams(query: LeadListQuery) {
    return buildHttpParams({
      stage: query.stage,
      status: query.status,
      assigned_to: query.assigned_to,
      unassigned_only: query.unassigned_only ? true : undefined,
      q: query.q,
      source: query.source,
      last_activity_lt: query.last_activity_lt,
      last_activity_gt: query.last_activity_gt,
      // Leads Center toolbar filters. These were being built in
      // `leads.page.ts:buildQuery` but silently dropped here — the
      // date-range and remarks-note filters never reached the
      // backend. Result: the Date (from) / Between (to) pickers
      // rendered but the list ignored them.
      created_from: query.created_from,
      created_to: query.created_to,
      remarks_contains: query.remarks_contains,
      sort: query.sort,
      order: query.order,
      page: query.page,
      size: query.size,
      cursor: query.cursor,
      limit: query.limit,
      with_total: query.with_total,
      with_unfiltered_total: query.with_unfiltered_total,
      filter:
        query.filter && !isEmptyFilter(query.filter) ? JSON.stringify(query.filter) : undefined,
      ...prefixCustomFilters(query.customFilters),
    });
  }
}
