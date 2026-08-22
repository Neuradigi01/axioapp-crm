/**
 * Inline WhatsApp template picker for the compose bar. Shown only
 * when the conversation is on WhatsApp and outside the 24-hour
 * session window — Meta's rule is that only approved templates can
 * be sent outside the window.
 *
 * Flow:
 *   1. Button opens a popover listing APPROVED templates from the
 *      central library (`GET /api/v1/templates?channel=whatsapp&
 *      external_status=approved&is_active=true`). Reads the same
 *      surface the templates page authors into, so operator-created
 *      WA templates appear here the moment Meta approves them.
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

import { TemplateRead, TemplatesApiService } from '../templates/templates-api.service';
import { ConversationMessage, ConversationsApiService } from './conversations-api.service';

/** Display shape the picker template renders. Adapts a central
 *  library ``TemplateRead`` into the exact fields the popover markup
 *  reads — keeps the HTML unchanged when the data source moved from
 *  the legacy WA-only endpoint to the central library. */
interface PickerRow {
  id: string;
  name: string;
  category: string;
  language: string;
  body: string;
  variable_count: number;
  header_text: string | null;
  footer_text: string | null;
}

/** Positional Meta placeholder ``{{n}}`` regex — matches the pattern
 *  the WA extension row's ``variable_count`` counts. Named CRM vars
 *  like ``{{contact.first_name}}`` are resolved server-side from the
 *  conversation's contact + org, so they contribute zero operator
 *  input slots. */
const POSITIONAL_VAR_RE = /\{\{\s*(\d+)\s*\}\}/g;

function positionalVariableCount(body: string): number {
  const seen = new Set<number>();
  for (const match of body.matchAll(POSITIONAL_VAR_RE)) {
    seen.add(Number.parseInt(match[1], 10));
  }
  return seen.size;
}

function toPickerRow(t: TemplateRead): PickerRow {
  const wa = t.whatsapp ?? null;
  return {
    id: t.id,
    name: t.name,
    // Meta's WA category (marketing / utility / authentication) if
    // the extension row set one; fall back to the central row's
    // send-guard category so the badge is never blank.
    category: wa?.category ?? t.category,
    language: t.language,
    body: t.body_text,
    variable_count: positionalVariableCount(t.body_text),
    header_text: wa?.header_text ?? null,
    footer_text: wa?.footer_text ?? null,
  };
}

@Component({
  selector: 'app-whatsapp-template-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, FormsModule],
  templateUrl: './whatsapp-template-picker.component.html',
})
export class WhatsAppTemplatePickerComponent {
  private readonly templatesApi = inject(TemplatesApiService);
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
  protected readonly templates = signal<PickerRow[]>([]);
  protected readonly selected = signal<PickerRow | null>(null);
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

  protected pick(t: PickerRow): void {
    this.selected.set(t);
    // Reset variable inputs on switch — otherwise a slot value from
    // the previous template's index N would bleed into the new one.
    this.variableValues.set({});
    // Always drop into the preview panel — even for zero-variable
    // templates. Previously we auto-sent when the template had no
    // `{{n}}` slots, which meant a single click on a template row
    // fired an outbound WhatsApp message to the customer with no
    // confirmation step. The operator now always sees the preview +
    // an explicit "Send template" button before the send goes out.
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
    this.templatesApi
      .list({
        channel: 'whatsapp',
        external_status: 'approved',
        is_active: true,
        // 200 is the max the list endpoint allows. Any org with more
        // than 200 approved WA templates is already in "search me
        // first" territory — the popover has a client-side filter
        // for the visible slice.
        limit: 200,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.templates.set(res.items.map(toPickerRow));
          this.loading.set(false);
        },
        error: () => {
          this.loading.set(false);
        },
      });
  }
}
