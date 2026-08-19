/**
 * Styling tab (``tasks/ai-assistants`` Step 13).
 *
 * Theme mode + assistant shape + 8 colour swatches + header profile
 * picture upload. Every editor-managed field writes into
 * ``styling_config`` via ``patchStylingConfig``; the preview pane
 * subscribes to the same signal store + re-renders on every stroke
 * with zero network calls.
 *
 * The profile-picture flow is out-of-band: the backend persists the
 * served URL via a targeted ``jsonb_set`` (independent of the OCC
 * version) so an operator can swap the avatar mid-edit without
 * losing dirty state on other fields. On success we call
 * ``setStylingConfigSilently`` so the preview re-renders without
 * flipping the Save button to dirty for a change already saved.
 */
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { AiAssistantsApiService } from '../../ai-assistants-api.service';
import { AssistantFormStateService } from '../../form-state.service';
import { ColorInputComponent } from './color-input.component';

// Keep in lock-step with the preview component's `_STYLING_DEFAULTS`.
const DEFAULTS = {
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
} as const;

// Client-side sanity check — matches the backend's 2 MB cap.
const MAX_IMAGE_BYTES = 2 * 1024 * 1024;
const ACCEPT_IMAGES = 'image/png,image/jpeg,image/webp';

function _str(cfg: Record<string, unknown>, key: string, fallback: string): string {
  const v = cfg[key];
  return typeof v === 'string' ? v : fallback;
}

interface ColorField {
  key: keyof typeof DEFAULTS;
  label: string;
  helpText: string | null;
}

const COLOR_FIELDS: readonly ColorField[] = [
  { key: 'assistant_bg', label: 'Assistant Background Color', helpText: null },
  { key: 'assistant_text', label: 'Assistant Text Color', helpText: null },
  { key: 'bg', label: 'Background Color', helpText: null },
  { key: 'cta_bg', label: 'CTA Buttons Color', helpText: null },
  {
    key: 'bubble_bg',
    label: 'Primary Chat Bubble Background Color',
    helpText: null,
  },
  { key: 'bubble_text', label: 'Primary Chat Bubble Text Color', helpText: null },
  { key: 'footer_bg', label: 'Footer Background Color', helpText: null },
  { key: 'footer_text', label: 'Footer Text Color', helpText: null },
];

@Component({
  selector: 'app-ai-assistant-styling-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule, ColorInputComponent],
  templateUrl: './styling-tab.component.html',
})
export class StylingTabComponent {
  private readonly api = inject(AiAssistantsApiService);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly formState = inject(AssistantFormStateService);

  protected readonly colorFields = COLOR_FIELDS;
  protected readonly maxImageBytes = MAX_IMAGE_BYTES;
  protected readonly acceptImages = ACCEPT_IMAGES;

  // --- Theme + shape --------------------------------------------------

  protected readonly themeMode = computed(() =>
    _str(this.formState.formState().styling_config, 'theme_mode', DEFAULTS.theme_mode),
  );

  protected readonly assistantShape = computed(() =>
    _str(this.formState.formState().styling_config, 'assistant_shape', DEFAULTS.assistant_shape),
  );

  protected onThemeChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.formState.patchStylingConfig({ theme_mode: value });
  }

  protected onShapeChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.formState.patchStylingConfig({ assistant_shape: value });
  }

  // --- Colour swatches -----------------------------------------------

  protected colorValue(field: ColorField): string {
    return _str(this.formState.formState().styling_config, field.key, DEFAULTS[field.key]);
  }

  protected onColorChange(field: ColorField, value: string): void {
    this.formState.patchStylingConfig({ [field.key]: value });
  }

  // --- Profile picture ------------------------------------------------

  protected readonly profilePictureUrl = computed(() => {
    const raw = this.formState.formState().styling_config['header_profile_picture_url'];
    return typeof raw === 'string' && raw.length > 0 ? raw : null;
  });

  protected readonly uploading = signal(false);
  protected readonly deleting = signal(false);
  protected readonly picError = signal<string | null>(null);

  protected onPickPicture(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    // Reset so re-selecting the same file after an error refires the change.
    input.value = '';
    if (!file) return;
    this.picError.set(null);
    if (file.size > MAX_IMAGE_BYTES) {
      this.picError.set('Image exceeds the 2 MB limit.');
      return;
    }
    const assistantId = this.formState.assistantId();
    if (!assistantId) {
      this.picError.set('Save the assistant before uploading a profile picture.');
      return;
    }
    this.uploading.set(true);
    this.api
      .uploadProfilePicture(assistantId, file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.uploading.set(false);
          // Backend already persisted via jsonb_set — write silently
          // so the Save button doesn't flip to dirty.
          this.formState.setStylingConfigSilently({
            header_profile_picture_url: resp.url,
          });
        },
        error: (err: HttpErrorResponse) => {
          this.uploading.set(false);
          this.picError.set(extractApiError(err) ?? 'Upload failed.');
        },
      });
  }

  protected removePicture(): void {
    const assistantId = this.formState.assistantId();
    if (!assistantId) return;
    this.picError.set(null);
    this.deleting.set(true);
    this.api
      .deleteProfilePicture(assistantId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deleting.set(false);
          // Mirror the DELETE by wiping the key locally too.
          this.formState.setStylingConfigSilently({
            header_profile_picture_url: null,
          });
        },
        error: (err: HttpErrorResponse) => {
          this.deleting.set(false);
          this.picError.set(extractApiError(err) ?? 'Delete failed.');
        },
      });
  }
}
