import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  EmbedApiService,
  EmbedKeyIssueResponse,
} from './embed-api.service';

/**
 * Two-phase modal:
 *   1. Form phase — optional name input + Issue button.
 *   2. Reveal phase — shows the plaintext secret ONCE in a copyable
 *      <code> block + a permanent warning + a "I've saved this key"
 *      checkbox that must be ticked before Close enables. This
 *      friction is deliberate: users WILL close the modal without
 *      copying if Close is enabled by default, and the secret is
 *      genuinely unrecoverable.
 *
 * Emits `issued` when a key has been issued (parent refreshes its
 * list) and `closed` when the user dismisses (also refresh, to
 * cover the case where they issued + closed without seeing the
 * `issued` event arrive).
 */
@Component({
  selector: 'app-embed-issue-key-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './issue-key-modal.component.html',
})
export class IssueKeyModalComponent {
  private readonly api = inject(EmbedApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** Parent toggles this to control visibility. */
  readonly open = input.required<boolean>();
  readonly issued = output<EmbedKeyIssueResponse>();
  readonly closed = output<void>();

  protected readonly name = signal('');
  protected readonly submitting = signal(false);
  protected readonly error = signal<string | null>(null);

  /** Set when the issue request succeeds. Drives the reveal phase. */
  protected readonly issuedKey = signal<EmbedKeyIssueResponse | null>(null);
  protected readonly savedConfirmed = signal(false);
  protected readonly copied = signal(false);

  protected readonly canClose = computed(
    () => this.issuedKey() === null || this.savedConfirmed(),
  );

  protected onNameInput(event: Event): void {
    this.name.set((event.target as HTMLInputElement).value);
  }

  protected onSavedToggle(event: Event): void {
    this.savedConfirmed.set((event.target as HTMLInputElement).checked);
  }

  protected submit(): void {
    if (this.submitting()) return;
    this.submitting.set(true);
    this.error.set(null);
    this.api
      .issueKey(this.name().trim() || null)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.submitting.set(false);
          this.issuedKey.set(resp);
          this.savedConfirmed.set(false);
          this.copied.set(false);
          this.issued.emit(resp);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.error.set(
            extractApiError(err) ?? 'Could not issue the key.',
          );
        },
      });
  }

  protected async copySecret(): Promise<void> {
    const key = this.issuedKey();
    if (!key) return;
    try {
      await navigator.clipboard.writeText(key.secret);
      this.copied.set(true);
    } catch {
      // Clipboard API requires HTTPS or localhost; fall back silently.
      // The secret is visible in the <code> block for manual copy.
      this.copied.set(false);
    }
  }

  protected close(): void {
    if (!this.canClose()) return;
    this.resetState();
    this.closed.emit();
  }

  private resetState(): void {
    this.name.set('');
    this.error.set(null);
    this.submitting.set(false);
    this.issuedKey.set(null);
    this.savedConfirmed.set(false);
    this.copied.set(false);
  }
}
