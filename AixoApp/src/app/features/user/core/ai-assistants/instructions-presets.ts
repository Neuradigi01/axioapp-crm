/**
 * Instruction-type dropdown labels (``tasks/ai-assistants`` Step 8).
 *
 * The dropdown's first option is always ``Custom Prompt`` (the
 * empty state where the operator writes their own prompt from
 * scratch). The remaining options come from the backend via
 * ``GET /templates?channel=ai_prompt`` — this file only carries
 * a tiny type + the canonical "Custom Prompt" sentinel so the
 * component can key on a stable value rather than a translated
 * string.
 */

/** Sentinel dropdown option — user writes a prompt from scratch. */
export const CUSTOM_PROMPT_ID = '__custom_prompt__';

/** Dropdown row shape rendered inside the Instructions tab. */
export interface InstructionPreset {
  /** Template id, or ``CUSTOM_PROMPT_ID`` for the sentinel row. */
  id: string;
  /** User-visible label. */
  label: string;
  /** The prompt body to paste into the textarea on selection.
   *  Empty string for the ``CUSTOM_PROMPT_ID`` row so selecting
   *  Custom Prompt is a no-op patch on the form-state. */
  body: string;
}
