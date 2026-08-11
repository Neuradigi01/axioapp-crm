/**
 * Inline WhatsApp template picker for the compose bar. Shown only
 * when the conversation is on WhatsApp and outside the 24-hour
 * session window — Meta's rule is that only approved templates can
 * be sent outside the window.
 *
 * Flow:
 *   1. Button opens a popover listing APPROVED templates
 *      (`GET /integrations/whatsapp/templates?status=APPROVED`).
 *   2. Selecting a template with zero variables sends immediately.
 *   3. Selecting a template with `{{n}}` placeholders expands an
 *      inline variables form; Send is disabled until every slot is
 *      filled.
 *   4. Send hits `POST /conversations/{id}/messages/template`; on
 *      success we emit `sent` so the parent can refetch the thread.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  HostListener,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  IntegrationsApiService,
  WhatsAppTemplate,
} from '../settings/integrations/integrations-api.service';
import { ConversationMessage, ConversationsApiService } from './conversations-api.service';

@Component({
  selector: 'app-whatsapp-template-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, FormsModule],
  templateUrl: './whatsapp-template-picker.component.html',
})
export class WhatsAppTemplatePickerComponent {
  private readonly integrationsApi = inject(IntegrationsApiService);
  private readonly conversationsApi = inject(ConversationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly conversationId = input.required<string>();
  readonly sendFromPhoneId = input<string | null>(null);

  readonly sent = output<ConversationMessage>();
  readonly errored = output<string>();

  protected readonly open = signal<boolean>(false);
  protected readonly loading = signal<boolean>(false);
  protected readonly sending = signal<boolean>(false);
  protected readonly search = signal<string>('');
  protected readonly templates = signal<WhatsAppTemplate[]>([]);
  protected readonly selected = signal<WhatsAppTemplate | null>(null);
  /** Variable slot values, indexed by `{{n}}` (1-based). */
  protected readonly variableValues = signal<Record<string, string>>({});
  /** Inline error message shown inside the popover — kept local so it
   *  stays visible next to the failing action even if the parent's
   *  header banner has scrolled off. Cleared on retry / close. */
  protected readonly errorMessage = signal<string | null>(null);

  /** Filtered list — client-side prefix match on template name so the
   *  picker feels instant. The full approved-templates list is small
   *  enough (~dozens) to hold in memory. */
  protected readonly filtered = computed(() => {
    const q = this.search().trim().toLowerCase();
    if (!q) return this.templates();
    return this.templates().filter((t) => t.name.toLowerCase().includes(q));
  });

  /** Substituted body preview shown above the variable inputs — the
   *  operator sees exactly what the customer will receive. */
  protected readonly renderedBody = computed(() => {
    const t = this.selected();
    if (!t) return '';
    let body = t.body ?? '';
    const values = this.variableValues();
    for (const [idx, val] of Object.entries(values)) {
      body = body.split('{{' + idx + '}}').join(val || '{{' + idx + '}}');
    }
    return body;
  });

  /** Variable-slot indices needed by the selected template — driven
   *  by `variable_count`. Empty when no template is selected or the
   *  template has zero variables. */
  protected readonly variableSlots = computed<number[]>(() => {
    const t = this.selected();
    if (!t) return [];
    return Array.from({ length: t.variable_count }, (_, i) => i + 1);
  });

  protected readonly canSend = computed<boolean>(() => {
    const t = this.selected();
    if (!t || this.sending()) return false;
    const values = this.variableValues();
    return this.variableSlots().every((idx) => (values[String(idx)] ?? '').trim().length > 0);
  });

  toggle(): void {
    const next = !this.open();
    this.open.set(next);
    if (next && this.templates().length === 0) {
      this._load();
    }
  }

  close(): void {
    this.open.set(false);
    this.selected.set(null);
    this.variableValues.set({});
    this.search.set('');
    this.errorMessage.set(null);
  }

  protected dismissError(): void {
    this.errorMessage.set(null);
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (!this.open()) return;
    const target = event.target as Element | null;
    if (target && target.closest('app-whatsapp-template-picker')) return;
    this.close();
  }

  protected pick(t: WhatsAppTemplate): void {
    this.selected.set(t);
    // Reset variable inputs on switch — otherwise a slot value from
    // the previous template's index N would bleed into the new one.
    this.variableValues.set({});
    if (t.variable_count === 0) {
      // No variables — send straight through.
      this.send();
    }
  }

  protected clearSelection(): void {
    this.selected.set(null);
    this.variableValues.set({});
  }

  protected patchVariable(idx: number, value: string): void {
    this.variableValues.update((current) => ({ ...current, [String(idx)]: value }));
  }

  protected send(): void {
    const t = this.selected();
    if (!t || !this.canSend()) return;
    this.sending.set(true);
    this.errorMessage.set(null);
    this.conversationsApi
      .sendTemplate(this.conversationId(), {
        templateId: t.id,
        variables: this.variableValues(),
        sendFromPhoneId: this.sendFromPhoneId(),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (msg) => {
          this.sending.set(false);
          this.sent.emit(msg);
          this.close();
        },
        error: (err: HttpErrorResponse) => {
          this.sending.set(false);
          const message = extractApiError(err) ?? 'Could not send template.';
          // Show inline in the popover for context AND bubble up so the
          // parent's header banner + audit stays consistent.
          this.errorMessage.set(message);
          this.errored.emit(message);
        },
      });
  }

  protected onSearchChange(value: string): void {
    this.search.set(value);
  }

  private _load(): void {
    this.loading.set(true);
    this.integrationsApi
      .listWhatsAppTemplates({ status: 'APPROVED' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.templates.set(rows);
          this.loading.set(false);
        },
        error: () => {
          this.loading.set(false);
        },
      });
  }
}
