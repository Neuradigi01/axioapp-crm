/**
 * Field-type union mirrors `CustomFieldDefinitionOut.field_type` from the
 * backend (`src.app.core.custom_fields.models`). Keep these two in sync —
 * the dynamic form rejects unknown types at render time.
 */
export type FieldType =
  | 'text'
  | 'number'
  | 'select'
  | 'multiselect'
  | 'date'
  | 'datetime'
  | 'boolean'
  | 'phone'
  | 'email'
  | 'currency';

export type FieldSource = 'system' | 'pack' | 'user';

export interface FieldOptions {
  choices?: string[];
  [k: string]: unknown;
}

/**
 * Shape that the dynamic form consumes for each field. Trimmed mirror of
 * `CustomField` from `custom-fields-api.service.ts` — only the bits the
 * renderer + validator translator need.
 */
export interface FieldDef {
  field_key: string;
  field_label: string;
  field_type: FieldType;
  options?: FieldOptions | null;
  is_required?: boolean;
  is_hidden?: boolean;
  display_order?: number;
  validation?: ValidationRules | null;
}

/**
 * The subset of validation keys the backend currently emits. The shape is
 * intentionally open (`Record<string, unknown>`) on the API side, so we
 * defensively read each key.
 */
export interface ValidationRules {
  min?: number;
  max?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  [k: string]: unknown;
}

export type FieldValue = string | number | boolean | string[] | null;

export type FormValue = Record<string, FieldValue>;
