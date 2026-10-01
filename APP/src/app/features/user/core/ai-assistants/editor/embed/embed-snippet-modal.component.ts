/**
 * Embed snippet modal (``tasks/ai-assistants`` Step 15).
 *
 * Opened from the editor header's Embed button. Shows the
 * copy-and-paste snippet, the list of issued keys, and lets the
 * operator issue / rotate / revoke keys.
 *
 * The plaintext ``secret`` for a freshly-issued (or rotated) key is
 * shown ONCE — the backend never surfaces it again. We surface a
 * "Copy secret" banner that expires with the modal so an operator
 * who navigates away without copying has to rotate to see another
 * plaintext key.
 */
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  HostListener,
  Input,
  OnInit,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '@shared/components/toast/toast.service';
import { ConfirmDialogService } from '../../../shared/confirm-dialog/confirm-dialog.service';
import { environment } from '../../../../../../../environments/environment';
import {
  AiAssistantsApiService,
  EmbedKeyIssueResponse,
  EmbedKeyRow,
} from '../../ai-assistants-api.service';

/** Derive the widget host from apiBaseUrl. Production ships the
 *  widget on ``widget.neuradigi.com`` (per convention); dev shares
 *  the API host for a single-origin dev experience. Operators can
 *  edit the snippet before pasting anyway. */
function _widgetHost(): string {
  const base = environment.apiBaseUrl.replace(/\/api\/v1\/?$/, '');
  return `${base}/widget`;
}

/** The API base URL that the widget must hit for session-init +
 *  message streaming (the ``data-host`` snippet attribute). Defaults
 *  to the CRM instance's own API host — snippets copied out of THIS
 *  instance route back to THIS instance's public endpoints. Without
 *  this, the widget falls back to the ``DEFAULT_HOST`` hard-coded in
 *  ``widget/src/loader.ts`` (production furnicrm.app) and 404s on any
 *  self-hosted / dev / staging deployment. */
function _apiHost(): string {
  return environment.apiBaseUrl.replace(/\/api\/v1\/?$/, '');
}

@Component({
  selector: 'app-embed-snippet-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  templateUrl: './embed-snippet-modal.component.html',
})
export class EmbedSnippetModalComponent implements OnInit {
  private readonly api = inject(AiAssistantsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);
  private readonly confirmDialog = inject(ConfirmDialogService);
  /** True while a rotate/revoke confirm is up, so Esc doesn't close this modal behind it. */
  private confirming = false;

  @Input({ required: true }) assistantId!: string;
  @Output() readonly dismissed = new EventEmitter<void>();

  protected readonly loading = signal(true);
  protected readonly keys = signal<EmbedKeyRow[]>([]);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  /** Plaintext secret from the most recent issue / rotate. Cleared
   *  when the modal closes so a stale copy doesn't linger. */
  protected readonly freshSecret = signal<string | null>(null);
  protected readonly copyState = signal<'idle' | 'copied'>('idle');

  protected readonly widgetHost = _widgetHost();
  protected readonly apiHost = _apiHost();

  /** The most-recent live key — used to build the default snippet. */
  protected readonly primaryKey = computed<EmbedKeyRow | null>(() => {
    const live = this.keys().filter((k) => !k.revoked_at);
    if (live.length > 0) return live[0];
    return null;
  });

  /** The snippet HTML string. Uses ``freshSecret`` when available
   *  (just-issued key) so the operator sees the copy-once plaintext;
   *  otherwise reads the primary key's prefix as a placeholder so
   *  the shape is visible even without a plaintext to embed. */
  protected readonly snippet = computed<string>(() => {
    const fresh = this.freshSecret();
    const key = this.primaryKey();
    const keyStr =
      fresh ?? (key ? `${key.prefix}<COPY-ONCE-SECRET-ROTATE-TO-SEE-AGAIN>` : 'YOUR_KEY');
    return `<div id="crm-ai-assistant"></div>
<script
  src="${this.widgetHost}/v1/widget.js"
  data-key="${keyStr}"
  data-host="${this.apiHost}"
  data-mount="crm-ai-assistant"
  defer
></script>`;
  });

  // Fetch keys in ngOnInit, NOT the constructor — Angular sets
  // ``@Input`` values after construction but before ngOnInit, so
  // ``this.assistantId`` is ``undefined`` inside the constructor and the
  // URL template literal would resolve to ``/embed/ai-assistants/undefined/keys``.
  ngOnInit(): void {
    this.refresh();
  }

  protected refresh(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .listEmbedKeys(this.assistantId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.keys.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load embed keys.');
        },
      });
  }

  protected issue(): void {
    this.busy.set(true);
    this.error.set(null);
    this.api
      .issueEmbedKey(this.assistantId, { allowed_origins: [] })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.busy.set(false);
          this.freshSecret.set(resp.secret);
          this.refresh();
          this.toast.success('Embed key issued', { subtitle: 'Copy the snippet below.' });
        },
        error: (err: HttpErrorResponse) => {
          this.busy.set(false);
          this.error.set(extractApiError(err) ?? 'Could not issue key.');
        },
      });
  }

  protected async rotate(key: EmbedKeyRow, graceDays = 0): Promise<void> {
    const ok = await this.ask({
      title: 'Rotate this key?',
      body:
        graceDays > 0
          ? `The old key stays live for ${graceDays} days so you can swap the snippet.`
          : 'The old key stops working immediately — update the snippet on your site.',
      confirmLabel: 'Rotate',
      danger: graceDays === 0,
    });
    if (!ok) return;
    this.busy.set(true);
    this.error.set(null);
    this.api
      .rotateEmbedKey(key.id, graceDays)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp: EmbedKeyIssueResponse) => {
          this.busy.set(false);
          this.freshSecret.set(resp.secret);
          this.refresh();
          this.toast.success('Key rotated', { subtitle: 'Copy the new snippet below.' });
        },
        error: (err: HttpErrorResponse) => {
          this.busy.set(false);
          this.error.set(extractApiError(err) ?? 'Rotate failed.');
        },
      });
  }

  protected async revokeNow(key: EmbedKeyRow): Promise<void> {
    const ok = await this.ask({
      title: 'Revoke this key now?',
      body: 'Chat sessions using this key are dropped immediately. This cannot be undone.',
      confirmLabel: 'Revoke',
      danger: true,
    });
    if (!ok) return;
    this.busy.set(true);
    this.error.set(null);
    this.api
      .revokeEmbedKeyNow(key.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.refresh();
          this.toast.success('Key revoked');
        },
        error: (err: HttpErrorResponse) => {
          this.busy.set(false);
          this.error.set(extractApiError(err) ?? 'Revoke failed.');
        },
      });
  }

  protected async copySnippet(): Promise<void> {
    const text = this.snippet();
    try {
      await navigator.clipboard.writeText(text);
      this.copyState.set('copied');
      // Reset after a moment so a subsequent copy also flashes.
      setTimeout(() => this.copyState.set('idle'), 1500);
    } catch {
      this.toast.error('Clipboard access blocked', {
        subtitle: 'Select the snippet and copy it manually.',
      });
    }
  }

  private async ask(opts: Parameters<ConfirmDialogService['ask']>[0]): Promise<boolean> {
    this.confirming = true;
    try {
      return await this.confirmDialog.ask(opts);
    } finally {
      this.confirming = false;
    }
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    if (!this.confirming) this.close();
  }

  protected close(): void {
    if (this.busy()) return;
    // Wipe the fresh secret on close — the operator loses their
    // last-chance-to-copy affordance so it's not floating in memory.
    this.freshSecret.set(null);
    this.dismissed.emit();
  }

  protected keyStatusPill(key: EmbedKeyRow): string {
    if (!key.revoked_at) {
      return 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20';
    }
    if (key.grace_expires_at) {
      return 'bg-amber-500/10 text-amber-400 ring-amber-500/20';
    }
    return 'bg-red-500/10 text-red-400 ring-red-500/20';
  }

  protected keyStatusLabel(key: EmbedKeyRow): string {
    if (!key.revoked_at) return 'Live';
    if (key.grace_expires_at) return 'Grace';
    return 'Revoked';
  }
}
