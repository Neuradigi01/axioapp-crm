/**
 * Settings → Integrations → AI Providers → Add Key modal
 * (``tasks/ai-assistants`` Step 3).
 *
 * Adds a new BYOK OpenAI API key. v1 supports OpenAI only; the
 * other three provider options render disabled with a "Coming soon"
 * chip so the user understands the shape of the future feature
 * without being able to submit an unsupported provider.
 *
 * Save-then-test flow: POST creates the row; on success we
 * immediately POST the ``/test`` endpoint (Step 2's real probe)
 * and surface the outcome inline. After a successful save the
 * ``saved`` output emits and the parent closes the modal + refreshes
 * the list.
 *
 * The full API key is bound to a signal that gets cleared on close
 * so it never lingers in memory. After POST returns, the response
 * carries only the masked ``last4`` — the plaintext key never
 * appears in the DOM again.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  inject,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { AutofillEvent, TextFieldModule } from '@angular/cdk/text-field';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { AiProvider, AiProviderKey, AiProvidersApiService } from './ai-providers-api.service';

interface ProviderOption {
  value: AiProvider;
  label: string;
  disabled: boolean;
}

@Component({
  selector: 'app-ai-providers-add-key-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, TextFieldModule, LucideAngularModule],
  templateUrl: './ai-providers-add-key-modal.component.html',
})
export class AiProvidersAddKeyModalComponent {
  private readonly api = inject(AiProvidersApiService);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  /** Emitted after the modal saves + tests successfully. Parent
   *  closes the modal + refetches the keys list. */
  readonly saved = output<AiProviderKey>();
  /** Emitted when the user dismisses without saving. */
  readonly closed = output<void>();

  protected readonly providers: ProviderOption[] = [
    { value: 'openai', label: 'OpenAI', disabled: false },
    { value: 'anthropic', label: 'Anthropic (Coming soon)', disabled: true },
    { value: 'google', label: 'Google (Coming soon)', disabled: true },
    { value: 'openrouter', label: 'OpenRouter (Coming soon)', disabled: true },
  ];

  protected readonly form = this.fb.nonNullable.group({
    provider: this.fb.nonNullable.control<AiProvider>('openai'),
    label: this.fb.nonNullable.control<string>('Default'),
    api_key: this.fb.nonNullable.control<string>('', {
      validators: [Validators.required, Validators.minLength(8)],
    }),
  });

  protected readonly showApiKey = signal(false);
  protected readonly saving = signal(false);
  protected readonly savedKey = signal<AiProviderKey | null>(null);
  protected readonly testing = signal(false);
  protected readonly submitError = signal<string | null>(null);
  protected readonly duplicateInfo = signal<{ last4: string } | null>(null);

  // Ref to the raw <input> so we can read the live DOM value at submit
  // time — the reactive form control can lag behind on browser autofill
  // or paste on `type="password"` fields.
  private readonly apiKeyInput = viewChild<ElementRef<HTMLInputElement>>('apiKeyInput');

  // Dim styling only — the button is always clickable so we can sync
  // the DOM value and surface a validation message on click if empty.
  protected readonly canSave = computed(
    () => this.form.valid && !this.saving() && this.savedKey() === null,
  );

  protected toggleReveal(): void {
    this.showApiKey.update((v) => !v);
  }

  // Chromium does not fire `input` when it autofills a `type="password"`
  // field, so the reactive form control stays empty and Save + test stays
  // disabled even though dots are visible. `cdkAutofill` from Angular CDK
  // detects the autofill and lets us push the DOM value into the control.
  protected onApiKeyAutofill(event: AutofillEvent): void {
    if (!event.isAutofilled) return;
    const input = event.target as HTMLInputElement;
    const control = this.form.controls.api_key;
    if (control.value !== input.value) {
      control.setValue(input.value);
      control.markAsDirty();
    }
  }

  protected save(): void {
    if (this.saving() || this.savedKey() !== null) return;

    // Belt-and-suspenders: force-sync the live DOM value into the reactive
    // form control before validating. Chromium/Safari don't always fire
    // `input` on autofill or programmatic paste into `type="password"`,
    // which would otherwise leave the control empty and validation failing.
    const inputEl = this.apiKeyInput()?.nativeElement;
    if (inputEl) {
      const control = this.form.controls.api_key;
      if (control.value !== inputEl.value) {
        control.setValue(inputEl.value);
        control.markAsDirty();
      }
    }

    if (!this.form.valid) {
      this.form.markAllAsTouched();
      this.submitError.set('Enter your OpenAI API key (min. 8 characters).');
      return;
    }

    this.saving.set(true);
    this.submitError.set(null);
    this.duplicateInfo.set(null);

    const raw = this.form.getRawValue();
    this.api
      .create({
        provider: raw.provider,
        label: raw.label.trim() || 'Default',
        api_key: raw.api_key,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.saving.set(false);
          this.savedKey.set(row);
          // Purge the plaintext key from the form the moment we've
          // handed it off — no reason it should linger in memory.
          this.form.patchValue({ api_key: '' });
          this.showApiKey.set(false);
          // Kick off the connectivity probe automatically. If it
          // succeeds, the parent auto-closes; if it fails, the
          // operator sees the reason and can decide to keep or
          // delete the key.
          this._runTest(row);
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          if (err.status === 409 && this._isDuplicate(err.error)) {
            this.duplicateInfo.set({ last4: err.error?.detail?.last4 ?? '' });
          } else {
            this.submitError.set(extractApiError(err) ?? 'Could not save API key.');
          }
        },
      });
  }

  protected close(): void {
    if (this.saving() || this.testing()) return;
    const saved = this.savedKey();
    if (saved !== null) {
      this.saved.emit(saved);
    } else {
      this.closed.emit();
    }
  }

  private _runTest(row: AiProviderKey): void {
    this.testing.set(true);
    this.api
      .test(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.testing.set(false);
          this.savedKey.set(updated);
          // Auto-close on green — the parent refetches.
          if (updated.test_status === 'success') {
            this.saved.emit(updated);
          }
          // On failure, leave the modal open so the user reads the
          // detail then chooses to close (still saves the key row —
          // matches Pabbly reference behaviour).
        },
        error: (err: HttpErrorResponse) => {
          this.testing.set(false);
          this.submitError.set(extractApiError(err) ?? 'Test failed.');
        },
      });
  }

  private _isDuplicate(body: unknown): boolean {
    // FastAPI wraps the service's HTTPException detail under
    // ``body.detail`` — the shape we throw is
    // ``{"reason":"key_already_stored","existing_key_id":..,"last4":..}``.
    return (
      typeof body === 'object' &&
      body !== null &&
      'detail' in body &&
      typeof (body as { detail: unknown }).detail === 'object' &&
      (body as { detail: { reason?: string } }).detail?.reason === 'key_already_stored'
    );
  }
}
