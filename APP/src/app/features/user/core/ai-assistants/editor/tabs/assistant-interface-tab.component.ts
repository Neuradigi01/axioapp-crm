/**
 * Assistant Interface tab (``tasks/ai-assistants`` Step 12).
 *
 * Six fields grouped into three visual sections mirroring the
 * Pabbly Chatflow reference:
 *
 *   * **Header** — heading + subheading strings the widget renders
 *     at the top of the chat frame.
 *   * **Initial Messages** — up to 2 chip bubbles the widget shows
 *     before the user has typed anything (Pabbly caps at 2; we
 *     match). Server accepts more via the JSONB blob, but the tab
 *     UI enforces the cap so the preview matches the widget.
 *   * **Footer** — Powered-by toggle + footer text + footer link.
 *     User-facing label reads "Powered by CRM" per the branding
 *     memory (backend key stays ``show_powered_by``).
 *
 * All writes flow into ``interface_config`` via the form-state
 * ``patchInterfaceConfig`` helper — a shallow merge so a change to
 * one field never drops sibling keys. The live-preview pane
 * (Step 7's ``AssistantPreviewComponent``) subscribes to the same
 * signal store and re-renders instantly with zero network calls.
 */
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { AssistantFormStateService } from '../../form-state.service';

const HEADING_MAX = 120;
const SUBHEADING_MAX = 200;
const FOOTER_TEXT_MAX = 60;
const FOOTER_LINK_MAX = 500;
const INITIAL_MESSAGE_MAX = 240;
const INITIAL_MESSAGES_LIMIT = 2;

// Defaults mirror the preview component's defaults so the tab UI
// shows the exact string the widget will render out-of-the-box.
const DEFAULTS = {
  header_heading: 'Your Brand Name 👋',
  header_subheading: "We're online and happy to assist you!",
  initial_message: 'Hi there! 👋 How can I help you today?',
  footer_text: 'Privacy Policy',
  footer_link: 'https://www.example.com/privacy-policy/',
} as const;

/** Defensively read a string sub-key from the config JSONB. Empty +
 *  non-strings collapse to the default so the input controls always
 *  have a bound value even when the assistant was created before
 *  this tab existed. */
function _str(cfg: Record<string, unknown>, key: string, fallback: string): string {
  const v = cfg[key];
  return typeof v === 'string' ? v : fallback;
}

function _bool(cfg: Record<string, unknown>, key: string, fallback: boolean): boolean {
  const v = cfg[key];
  return typeof v === 'boolean' ? v : fallback;
}

function _stringList(cfg: Record<string, unknown>, key: string, fallback: string[]): string[] {
  const v = cfg[key];
  if (Array.isArray(v) && v.every((x) => typeof x === 'string')) return v;
  return fallback;
}

@Component({
  selector: 'app-ai-assistant-interface-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  templateUrl: './assistant-interface-tab.component.html',
})
export class AssistantInterfaceTabComponent {
  protected readonly formState = inject(AssistantFormStateService);

  protected readonly headingMax = HEADING_MAX;
  protected readonly subheadingMax = SUBHEADING_MAX;
  protected readonly footerTextMax = FOOTER_TEXT_MAX;
  protected readonly footerLinkMax = FOOTER_LINK_MAX;
  protected readonly initialMessageMax = INITIAL_MESSAGE_MAX;
  protected readonly initialMessagesLimit = INITIAL_MESSAGES_LIMIT;

  // Every field is a computed that reads the JSONB defensively so
  // the tab is fully re-hydrateable from a partial config saved by
  // an older client (or the seed default).
  protected readonly headerHeading = computed(() =>
    _str(this.formState.formState().interface_config, 'header_heading', DEFAULTS.header_heading),
  );
  protected readonly headerSubheading = computed(() =>
    _str(
      this.formState.formState().interface_config,
      'header_subheading',
      DEFAULTS.header_subheading,
    ),
  );
  protected readonly initialMessages = computed(() =>
    _stringList(this.formState.formState().interface_config, 'initial_messages', [
      DEFAULTS.initial_message,
    ]),
  );
  protected readonly showPoweredBy = computed(() =>
    _bool(this.formState.formState().interface_config, 'show_powered_by', true),
  );
  protected readonly footerText = computed(() =>
    _str(this.formState.formState().interface_config, 'footer_text', DEFAULTS.footer_text),
  );
  protected readonly footerLink = computed(() =>
    _str(this.formState.formState().interface_config, 'footer_link', DEFAULTS.footer_link),
  );

  protected readonly canAddInitialMessage = computed(
    () => this.initialMessages().length < INITIAL_MESSAGES_LIMIT,
  );

  // --- Field handlers ------------------------------------------------

  protected onHeaderHeadingInput(event: Event): void {
    const raw = (event.target as HTMLInputElement).value;
    this.formState.patchInterfaceConfig({ header_heading: raw });
  }

  protected onHeaderSubheadingInput(event: Event): void {
    const raw = (event.target as HTMLInputElement).value;
    this.formState.patchInterfaceConfig({ header_subheading: raw });
  }

  protected onInitialMessageInput(index: number, event: Event): void {
    const raw = (event.target as HTMLInputElement).value;
    const current = this.initialMessages();
    if (index < 0 || index >= current.length) return;
    const next = [...current];
    next[index] = raw;
    this.formState.patchInterfaceConfig({ initial_messages: next });
  }

  /** Draft text for the "+ Add Message" row. Kept local so an empty
   *  string in the draft doesn't spawn an empty chip. */
  protected readonly addDraft = signal('');

  protected onAddDraftInput(event: Event): void {
    this.addDraft.set((event.target as HTMLInputElement).value);
  }

  protected onAddDraftKey(event: KeyboardEvent): void {
    if (event.key === 'Enter' && this.addDraft().trim()) {
      event.preventDefault();
      this.addInitialMessage();
    }
  }

  protected addInitialMessage(): void {
    const raw = this.addDraft().trim();
    if (!raw) return;
    if (!this.canAddInitialMessage()) return;
    this.formState.patchInterfaceConfig({
      initial_messages: [...this.initialMessages(), raw],
    });
    this.addDraft.set('');
  }

  protected removeInitialMessage(index: number): void {
    const current = this.initialMessages();
    if (index < 0 || index >= current.length) return;
    const next = current.filter((_, i) => i !== index);
    this.formState.patchInterfaceConfig({ initial_messages: next });
  }

  protected onPoweredByChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.formState.patchInterfaceConfig({ show_powered_by: value === 'enabled' });
  }

  protected onFooterTextInput(event: Event): void {
    const raw = (event.target as HTMLInputElement).value;
    this.formState.patchInterfaceConfig({ footer_text: raw });
  }

  protected onFooterLinkInput(event: Event): void {
    const raw = (event.target as HTMLInputElement).value;
    this.formState.patchInterfaceConfig({ footer_link: raw });
  }
}
