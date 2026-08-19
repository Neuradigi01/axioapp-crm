/**
 * Editor-scoped form state for the AI Assistant editor
 * (``tasks/ai-assistants`` Step 7).
 *
 * A signal-based store that mirrors the assistant record shape.
 * Tabs write into it via ``patch()``; the live-preview pane
 * reads via the ``formState`` signal and re-renders on any
 * change with zero network calls.
 *
 * Provided at the editor page level (NOT ``root``) so a
 * new instance mounts on every navigation to a new assistant.
 * ``load()`` populates from a fetched ``AiAssistant``; ``dirty``
 * flips true on any change and back to false after a successful
 * save.
 *
 * v1 is explicit Save (matches Pabbly Chatflow); no autosave.
 * The Save button in the editor header reads ``buildUpdatePayload()``
 * and PATCHes.
 */
import { Injectable, computed, signal } from '@angular/core';

import {
  AiAssistant,
  AiAssistantUpdatePayload,
  LeadCaptureMode,
} from './ai-assistants-api.service';

/** Field-by-field editor state. All fields present so tabs can bind
 *  unconditionally; ``null`` means "not set" (defaults render in
 *  the preview). */
export interface AssistantFormState {
  name: string;
  description: string | null;
  key_id: string;
  model: string;
  temperature: number;
  instructions: string | null;
  stop_keywords: string[];
  retry_attempts: number;
  fallback_message: string;
  allowed_domains: string[];
  output_sanitizer_enabled: boolean;
  budget_cap_override_usd: number | null;
  lead_capture_mode: LeadCaptureMode;
  lead_capture_turn_n: number;
  lead_capture_message: string | null;
  interface_config: Record<string, unknown>;
  styling_config: Record<string, unknown>;
}

const _EMPTY_STATE: AssistantFormState = {
  name: '',
  description: null,
  key_id: '',
  model: 'gpt-4o-mini',
  temperature: 0.5,
  instructions: null,
  stop_keywords: [],
  retry_attempts: 0,
  fallback_message: "I'm sorry, I can't help with that right now.",
  allowed_domains: [],
  output_sanitizer_enabled: true,
  budget_cap_override_usd: null,
  lead_capture_mode: 'off',
  lead_capture_turn_n: 3,
  lead_capture_message: null,
  interface_config: {},
  styling_config: {},
};

@Injectable()
export class AssistantFormStateService {
  private readonly _state = signal<AssistantFormState>({ ..._EMPTY_STATE });
  private readonly _dirty = signal(false);
  private readonly _version = signal<number | null>(null);
  private readonly _assistantId = signal<string | null>(null);
  private readonly _status = signal<string | null>(null);
  private readonly _loaded = signal(false);

  /** The live editor state — every tab binds to this; the preview
   *  pane reads it and re-renders on any change. */
  readonly formState = this._state.asReadonly();
  readonly dirty = this._dirty.asReadonly();
  readonly version = this._version.asReadonly();
  readonly assistantId = this._assistantId.asReadonly();
  readonly status = this._status.asReadonly();
  readonly loaded = this._loaded.asReadonly();

  /** Convenience — tabs use these to preview merged tab-side changes. */
  readonly displayName = computed(() => this._state().name || 'Untitled Assistant');

  /** Reset + hydrate from an :class:`AiAssistant` fetched via the API. */
  load(row: AiAssistant): void {
    this._state.set({
      name: row.name,
      description: row.description,
      key_id: row.key_id,
      model: row.model,
      temperature: Number(row.temperature),
      instructions: row.instructions,
      stop_keywords: [...row.stop_keywords],
      retry_attempts: row.retry_attempts,
      fallback_message: row.fallback_message,
      allowed_domains: [...row.allowed_domains],
      output_sanitizer_enabled: row.output_sanitizer_enabled,
      budget_cap_override_usd:
        row.budget_cap_override_usd === null ? null : Number(row.budget_cap_override_usd),
      lead_capture_mode: row.lead_capture_mode,
      lead_capture_turn_n: row.lead_capture_turn_n,
      lead_capture_message: row.lead_capture_message,
      interface_config: { ...row.interface_config },
      styling_config: { ...row.styling_config },
    });
    this._version.set(row.version);
    this._assistantId.set(row.id);
    this._status.set(row.status);
    this._dirty.set(false);
    this._loaded.set(true);
  }

  /** Apply a partial patch. Called by every tab component when a
   *  field changes. Marks the store dirty; Save button becomes
   *  enabled. */
  patch(delta: Partial<AssistantFormState>): void {
    this._state.update((current) => ({ ...current, ...delta }));
    this._dirty.set(true);
  }

  /** Merge one or more keys into ``interface_config`` without
   *  clobbering the whole JSONB blob. Step 12's Interface tab uses
   *  this so each field-level ``onXInput`` handler stays a one-liner
   *  and doesn't accidentally drop sibling keys (initial_messages,
   *  show_powered_by, etc.). Step 13 uses the styling twin. */
  patchInterfaceConfig(delta: Record<string, unknown>): void {
    this._state.update((current) => ({
      ...current,
      interface_config: { ...current.interface_config, ...delta },
    }));
    this._dirty.set(true);
  }

  /** Styling twin of :meth:`patchInterfaceConfig`. Step 13's tab uses
   *  this for every colour swatch / theme dropdown so a change to
   *  one key doesn't wipe the sibling colours. Profile picture URL
   *  writes bypass the form-state (backend persists via jsonb_set
   *  out-of-band) — this helper is only for editor-driven fields. */
  patchStylingConfig(delta: Record<string, unknown>): void {
    this._state.update((current) => ({
      ...current,
      styling_config: { ...current.styling_config, ...delta },
    }));
    this._dirty.set(true);
  }

  /** Silent write: update the styling_config in-store WITHOUT
   *  flipping the dirty flag. Used by the profile-picture upload
   *  flow — the backend already persisted the URL via a targeted
   *  jsonb_set, so the operator hasn't actually made an unsaved
   *  edit to any editor-managed field. */
  setStylingConfigSilently(delta: Record<string, unknown>): void {
    this._state.update((current) => ({
      ...current,
      styling_config: { ...current.styling_config, ...delta },
    }));
  }

  /** Called after a successful PATCH round-trip. Re-hydrates from
   *  the server response (which carries the new ``version``) and
   *  clears the dirty flag so the Save button disables again. */
  applySaveResponse(row: AiAssistant): void {
    this.load(row);
  }

  /** Build the PATCH payload from current state. Includes every
   *  field the tabs manage — the backend's ``extra='forbid'`` is
   *  strict about the field set, so this list must stay in sync
   *  with :class:`AiAssistantUpdatePayload`. */
  buildUpdatePayload(): AiAssistantUpdatePayload {
    const s = this._state();
    const version = this._version();
    if (version === null) {
      throw new Error('cannot build update payload before load()');
    }
    return {
      version,
      name: s.name,
      description: s.description,
      key_id: s.key_id,
      model: s.model,
      temperature: s.temperature,
      instructions: s.instructions,
      stop_keywords: s.stop_keywords,
      retry_attempts: s.retry_attempts,
      fallback_message: s.fallback_message,
      allowed_domains: s.allowed_domains,
      output_sanitizer_enabled: s.output_sanitizer_enabled,
      budget_cap_override_usd: s.budget_cap_override_usd,
      lead_capture_mode: s.lead_capture_mode,
      lead_capture_turn_n: s.lead_capture_turn_n,
      lead_capture_message: s.lead_capture_message,
    };
  }

  /** Reset to the un-loaded state — used on navigation-away so a
   *  stale store doesn't render into the next editor mount. */
  reset(): void {
    this._state.set({ ..._EMPTY_STATE });
    this._version.set(null);
    this._assistantId.set(null);
    this._status.set(null);
    this._dirty.set(false);
    this._loaded.set(false);
  }
}
