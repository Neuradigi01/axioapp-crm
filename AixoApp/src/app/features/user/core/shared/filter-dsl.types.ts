/**
 * TypeScript mirror of the backend's filter DSL — keep aligned with
 * `api/src/app/core/leads/filter_dsl.py` (`LEAD_DIRECT_FIELDS`,
 * `CONTACT_JOINED_FIELDS`, `OPS`). The leads list endpoint and CSV
 * export consume this shape via the `filter` query param; the saved
 * views API will reuse it in Step 7.
 *
 * Contract: the wire format is exactly this object, JSON-encoded into
 * the `filter` query string. No camelCase ↔ snake_case adaptation.
 */

/** Fields the backend's filter DSL whitelists for leads. */
export type StandardFilterField =
  | 'status'
  | 'source'
  | 'assigned_to_id'
  | 'lead_score'
  | 'budget'
  | 'last_activity_at'
  | 'created_at'
  | 'expected_close_date'
  | 'pipeline_stage'
  | 'contact_name'
  | 'contact_phone'
  | 'contact_email';

/** Dotted custom-data access — `custom_data.<field_key>`. The backend
 * rejects keys not present in `custom_field_definitions` for the org. */
export type CustomFilterField = `custom_data.${string}`;

export type FilterField = StandardFilterField | CustomFilterField;

export type FilterOp =
  | 'eq'
  | 'neq'
  | 'in'
  | 'nin'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'contains'
  | 'starts_with'
  | 'between'
  | 'is_empty'
  | 'is_not_empty';

export interface FilterClause {
  field: FilterField;
  op: FilterOp;
  /** Omitted for `is_empty` / `is_not_empty`. `between` expects a
   * 2-element tuple; `in` / `nin` expect an array. */
  value?: unknown;
}

export interface FilterDsl {
  /** AND group. */
  all?: FilterClause[];
  /** OR group. v1 UI doesn't author this, but the backend accepts it
   * and Step 7 may emit it from saved-view imports. */
  any?: FilterClause[];
}

/** Count of authored clauses across both groups — used by the toolbar
 * badge so users can see "Advanced filter (3)" at a glance. */
export function clauseCount(dsl: FilterDsl | null | undefined): number {
  if (!dsl) return 0;
  return (dsl.all?.length ?? 0) + (dsl.any?.length ?? 0);
}

/** True when the DSL has no authored clauses (matches everything). */
export function isEmptyFilter(dsl: FilterDsl | null | undefined): boolean {
  return clauseCount(dsl) === 0;
}
