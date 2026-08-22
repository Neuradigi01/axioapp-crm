/**
 * Live-preview pane for the AI Assistant editor
 * (``tasks/ai-assistants`` Step 7).
 *
 * Reads :class:`AssistantFormStateService` signals and renders a
 * mock chat widget synchronously with **zero network calls**. As
 * Steps 12 + 13 fill the interface + styling tabs, this pane
 * reflects every change instantly.
 *
 * The mock conversation is one canned "Hi there! How can I help
 * you today?" bubble; Step 9's chat runtime hooks a real "Send"
 * flow into this component (the mock stays until then so the
 * preview never needs a valid key + budget to render).
 */
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { AssistantFormStateService } from '../../form-state.service';
import { PreviewStreamService } from './preview-stream.service';

interface PreviewMessage {
  role: 'user' | 'assistant';
  text: string;
  /** True on the assistant bubble while tokens are still arriving —
   *  the UI can render a subtle "typing…" indicator. */
  streaming?: boolean;
  /** Populated on ``error`` events — surfaces the reason in the
   *  bubble (e.g. "budget cap hit"). */
  errorReason?: string;
}

/** Sensible defaults so the preview renders even when the tabs
 *  haven't been touched. The interface + styling tabs write into
 *  ``interface_config`` / ``styling_config`` JSONB blobs; we read
 *  known keys defensively. */
interface InterfaceDefaults {
  header_heading: string;
  header_subheading: string;
  initial_messages: string[];
  show_powered_by: boolean;
  footer_text: string;
  footer_link: string;
}

interface StylingDefaults {
  theme_mode: 'light' | 'dark';
  assistant_shape: 'circle' | 'square';
  assistant_bg: string;
  assistant_text: string;
  bg: string;
  cta_bg: string;
  bubble_bg: string;
  bubble_text: string;
  footer_bg: string;
  footer_text: string;
  /** Widget-header profile picture URL. ``null`` renders the
   *  fallback sparkles icon (Step 13). */
  header_profile_picture_url: string | null;
}

const _INTERFACE_DEFAULTS: InterfaceDefaults = {
  header_heading: 'Your Brand Name 👋',
  header_subheading: "We're online and happy to assist you!",
  initial_messages: ['Hi there! 👋 How can I help you today?'],
  show_powered_by: true,
  footer_text: 'Privacy Policy',
  footer_link: 'https://www.example.com/privacy-policy/',
};

const _STYLING_DEFAULTS: StylingDefaults = {
  theme_mode: 'light',
  assistant_shape: 'circle',
  assistant_bg: '#128C7E',
  assistant_text: '#FFFFFF',
  bg: '#FFFFFF',
  cta_bg: '#25D366',
  bubble_bg: '#FEFEFE',
  bubble_text: '#1C252E',
  footer_bg: '#FFFFFF',
  footer_text: '#637381',
  header_profile_picture_url: null,
};

function _readString(config: Record<string, unknown>, key: string, fallback: string): string {
  const v = config[key];
  return typeof v === 'string' && v.length > 0 ? v : fallback;
}

/** Like ``_readString`` but permits a nullable field. Empty strings
 *  collapse to ``null`` so the template's ``@if`` renders the
 *  fallback icon instead of an ``<img src="">``. */
function _readStringOrNull(config: Record<string, unknown>, key: string): string | null {
  const v = config[key];
  return typeof v === 'string' && v.length > 0 ? v : null;
}

function _readStringList(
  config: Record<string, unknown>,
  key: string,
  fallback: string[],
): string[] {
  const v = config[key];
  if (Array.isArray(v) && v.every((x) => typeof x === 'string')) return v;
  return fallback;
}

function _readBool(config: Record<string, unknown>, key: string, fallback: boolean): boolean {
  const v = config[key];
  return typeof v === 'boolean' ? v : fallback;
}

function _readEnum<T extends string>(
  config: Record<string, unknown>,
  key: string,
  allowed: readonly T[],
  fallback: T,
): T {
  const v = config[key];
  if (typeof v === 'string' && (allowed as readonly string[]).includes(v)) return v as T;
  return fallback;
}

@Component({
  selector: 'app-ai-assistant-preview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './assistant-preview.component.html',
})
export class AssistantPreviewComponent {
  protected readonly formState = inject(AssistantFormStateService);

  protected readonly iface = computed<InterfaceDefaults>(() => {
    const cfg = this.formState.formState().interface_config;
    return {
      header_heading: _readString(cfg, 'header_heading', _INTERFACE_DEFAULTS.header_heading),
      header_subheading: _readString(
        cfg,
        'header_subheading',
        _INTERFACE_DEFAULTS.header_subheading,
      ),
      initial_messages: _readStringList(
        cfg,
        'initial_messages',
        _INTERFACE_DEFAULTS.initial_messages,
      ),
      show_powered_by: _readBool(cfg, 'show_powered_by', _INTERFACE_DEFAULTS.show_powered_by),
      footer_text: _readString(cfg, 'footer_text', _INTERFACE_DEFAULTS.footer_text),
      footer_link: _readString(cfg, 'footer_link', _INTERFACE_DEFAULTS.footer_link),
    };
  });

  protected readonly styling = computed<StylingDefaults>(() => {
    const cfg = this.formState.formState().styling_config;
    return {
      theme_mode: _readEnum(
        cfg,
        'theme_mode',
        ['light', 'dark'] as const,
        _STYLING_DEFAULTS.theme_mode,
      ),
      assistant_shape: _readEnum(
        cfg,
        'assistant_shape',
        ['circle', 'square'] as const,
        _STYLING_DEFAULTS.assistant_shape,
      ),
      assistant_bg: _readString(cfg, 'assistant_bg', _STYLING_DEFAULTS.assistant_bg),
      assistant_text: _readString(cfg, 'assistant_text', _STYLING_DEFAULTS.assistant_text),
      bg: _readString(cfg, 'bg', _STYLING_DEFAULTS.bg),
      cta_bg: _readString(cfg, 'cta_bg', _STYLING_DEFAULTS.cta_bg),
      bubble_bg: _readString(cfg, 'bubble_bg', _STYLING_DEFAULTS.bubble_bg),
      bubble_text: _readString(cfg, 'bubble_text', _STYLING_DEFAULTS.bubble_text),
      footer_bg: _readString(cfg, 'footer_bg', _STYLING_DEFAULTS.footer_bg),
      footer_text: _readString(cfg, 'footer_text', _STYLING_DEFAULTS.footer_text),
      header_profile_picture_url: _readStringOrNull(cfg, 'header_profile_picture_url'),
    };
  });

  // --- Live-chat state (Step 9) --------------------------------------
  private readonly stream = inject(PreviewStreamService);

  /** Ordered list of user + assistant bubbles the operator has
   *  exchanged with the assistant during this preview session. */
  protected readonly messages = signal<PreviewMessage[]>([]);
  /** Current typed message in the input box. */
  protected readonly input = signal<string>('');
  /** True while a stream is in flight — disables the Send button
   *  and shows the "typing…" indicator on the trailing assistant
   *  bubble. */
  protected readonly streaming = signal<boolean>(false);
  /** Ties every message in one preview session together so the
   *  backend can group them into a single conversation row. */
  private readonly sessionToken = signal<string>(this._newSessionToken());

  protected readonly canSend = computed(
    () =>
      !this.streaming() && this.input().trim().length > 0 && this.formState.assistantId() !== null,
  );

  protected onInput(event: Event): void {
    this.input.set((event.target as HTMLInputElement).value);
  }

  protected onInputKey(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey && this.canSend()) {
      event.preventDefault();
      void this.send();
    }
  }

  protected clearChat(): void {
    this.messages.set([]);
    this.sessionToken.set(this._newSessionToken());
  }

  protected async send(): Promise<void> {
    const assistantId = this.formState.assistantId();
    const message = this.input().trim();
    if (!assistantId || !message) return;

    // Append the user bubble + a fresh empty assistant bubble in
    // one update so the UI shows both immediately.
    const nextAssistant: PreviewMessage = { role: 'assistant', text: '', streaming: true };
    this.messages.update((cur) => [...cur, { role: 'user', text: message }, nextAssistant]);
    this.input.set('');
    this.streaming.set(true);

    try {
      for await (const evt of this.stream.stream(assistantId, message, this.sessionToken())) {
        if (evt.type === 'token' && evt.delta) {
          this.messages.update((cur) => {
            const copy = [...cur];
            const last = copy[copy.length - 1];
            if (last && last.role === 'assistant') {
              copy[copy.length - 1] = { ...last, text: last.text + evt.delta };
            }
            return copy;
          });
        } else if (evt.type === 'error') {
          this.messages.update((cur) => {
            const copy = [...cur];
            const last = copy[copy.length - 1];
            if (last && last.role === 'assistant') {
              copy[copy.length - 1] = { ...last, errorReason: evt.reason ?? 'error' };
            }
            return copy;
          });
        }
      }
    } catch (err) {
      this.messages.update((cur) => {
        const copy = [...cur];
        const last = copy[copy.length - 1];
        if (last && last.role === 'assistant') {
          copy[copy.length - 1] = {
            ...last,
            errorReason: (err as Error)?.message ?? 'network error',
          };
        }
        return copy;
      });
    } finally {
      // Flip streaming off on the last bubble.
      this.messages.update((cur) => {
        const copy = [...cur];
        const last = copy[copy.length - 1];
        if (last && last.role === 'assistant') {
          copy[copy.length - 1] = { ...last, streaming: false };
        }
        return copy;
      });
      this.streaming.set(false);
    }
  }

  private _newSessionToken(): string {
    // Non-cryptographic — the backend uses this as a grouping key
    // only; auth is via the JWT on the request.
    return `preview-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  }
}
