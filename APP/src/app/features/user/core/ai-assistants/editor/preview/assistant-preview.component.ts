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
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { AssistantFormStateService } from '../../form-state.service';

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
};

function _readString(config: Record<string, unknown>, key: string, fallback: string): string {
  const v = config[key];
  return typeof v === 'string' && v.length > 0 ? v : fallback;
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
    };
  });
}
