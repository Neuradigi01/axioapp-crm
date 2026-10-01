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
import { ToastService } from '@shared/components/toast/toast.service';
import { ConfirmDialogService } from '../../../shared/confirm-dialog/confirm-dialog.service';
import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../../shared/forms/mobile-select.component';
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
  imports: [CommonModule, LucideAngularModule, ColorInputComponent, MobileSelectComponent],
  templateUrl: './styling-tab.component.html',
})
export class StylingTabComponent {
  private readonly api = inject(AiAssistantsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);
  private readonly confirmDialog = inject(ConfirmDialogService);
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

  // Options for the shared crm-mobile-select. Same component used by
  // appointments / contacts / leads so the styling-tab pickers match
  // the rest of the CRM instead of using OS-native <select> chrome.
  protected readonly themeOptions: readonly MobileSelectOption[] = [
    { value: 'light', label: 'Light' },
    { value: 'dark', label: 'Dark' },
  ];

  protected readonly shapeOptions: readonly MobileSelectOption[] = [
    { value: 'circle', label: 'Circle' },
    { value: 'square', label: 'Square' },
  ];

  protected onThemeChange(value: string): void {
    this.formState.patchStylingConfig({ theme_mode: value });
  }

  protected onShapeChange(value: string): void {
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

  protected onPickPicture(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    // Reset so re-selecting the same file after an error refires the change.
    input.value = '';
    if (!file) return;
    if (file.size > MAX_IMAGE_BYTES) {
      this.toast.warn('Image is too large', { subtitle: 'Profile pictures can be up to 2 MB.' });
      return;
    }
    const assistantId = this.formState.assistantId();
    if (!assistantId) {
      this.toast.warn('Save the assistant first', {
        subtitle: 'A profile picture can be added once the assistant is saved.',
      });
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
          this.toast.success('Profile picture updated');
        },
        error: (err: HttpErrorResponse) => {
          this.uploading.set(false);
          this.toast.error(extractApiError(err) ?? 'Upload failed.');
        },
      });
  }

  protected async removePicture(): Promise<void> {
    const assistantId = this.formState.assistantId();
    if (!assistantId) return;
    const ok = await this.confirmDialog.ask({
      title: 'Remove the profile picture?',
      body: 'The chat header falls back to the default avatar.',
      confirmLabel: 'Remove',
      danger: true,
    });
    if (!ok) return;
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
          this.toast.success('Profile picture removed');
        },
        error: (err: HttpErrorResponse) => {
          this.deleting.set(false);
          this.toast.error(extractApiError(err) ?? 'Could not remove the picture.');
        },
      });
  }
}
