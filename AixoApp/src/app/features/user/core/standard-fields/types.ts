/**
 * TypeScript shapes mirroring `api/src/app/core/standard_fields/schemas.py`.
 *
 * Backend is the source of truth. Keep these in sync — the Settings tab
 * and the form modals (Steps 5/6) rely on the field names matching the
 * server response one-to-one.
 */

/** Single string union of every overridable-prop token. Used to type-narrow
 * the `overridable_props` array element so consumers can `switch` on it
 * exhaustively. */
export type OverridableProp =
  | 'label'
  | 'placeholder'
  | 'help'
  | 'required'
  | 'hidden'
  | 'min'
  | 'max'
  | 'step'
  | 'display_order';

export type StandardFieldType =
  | 'text'
  | 'textarea'
  | 'email'
  | 'tel'
  | 'number'
  | 'currency'
  | 'date'
  | 'datetime'
  | 'select'
  | 'multiselect'
  | 'tags'
  | 'boolean';

/** One merged-defaults+override field from `GET /standard-fields/{entity}/render`. */
export interface StandardFieldRendered {
  entity: string;
  field_key: string;
  field_type: StandardFieldType;

  label: string;
  placeholder: string | null;
  help_text: string | null;
  is_required: boolean;
  is_hidden: boolean;
  min_value: number | null;
  max_value: number | null;
  step_value: number | null;
  display_order: number;

  backend_required: boolean;
  backend_validators: string[];

  is_overridden: boolean;
  overridable_props: OverridableProp[];
}

export interface StandardFieldRenderedListResponse {
  entity: string;
  items: StandardFieldRendered[];
}

/** PUT body. Server treats `undefined` and missing keys identically; sending
 *  `null` clears that prop (column → NULL = inherit registry default). */
export interface StandardFieldOverrideIn {
  label?: string | null;
  placeholder?: string | null;
  help_text?: string | null;
  is_required?: boolean | null;
  is_hidden?: boolean | null;
  min_value?: number | null;
  max_value?: number | null;
  step_value?: number | null;
  display_order?: number | null;
}

export interface StandardFieldOverrideOut {
  id: string;
  entity: string;
  field_key: string;
  label: string | null;
  placeholder: string | null;
  help_text: string | null;
  is_required: boolean | null;
  is_hidden: boolean | null;
  min_value: number | null;
  max_value: number | null;
  step_value: number | null;
  display_order: number | null;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  updated_by: string | null;
}

export interface StandardFieldEntity {
  entity: string;
  field_count: number;
}

export interface StandardFieldEntitiesResponse {
  items: StandardFieldEntity[];
}
