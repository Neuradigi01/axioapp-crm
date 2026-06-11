/**
 * Reusable template-picker — a button that opens a popover with the
 * org's email templates filtered by name. On select, calls
 * `/email/templates/{id}/render` and emits the rendered output to
 * the parent compose surface.
 *
 * Inputs (typed via `input.required`):
 *   - `contactId` — the recipient contact (required for variable
 *     substitution; if absent the picker disables itself with a
 *     helpful tooltip).
 *   - `leadId`    — optional lead id; populates `lead.*` variables.
 *
 * Output `templateSelected` carries `{subject, body_html, body_text,
 * variables_used}` — the same shape the editor's preview returns.
 * The parent compose bar reads `body_text` (or `body_html`,
 * depending on which channel the compose targets) and fills its
 * input.
 *
 * The popover is positioned absolute below the trigger button (right-
 * aligned) — no portal needed since the picker is mounted directly
 * inside the compose bar which is itself sticky at the bottom.
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
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { extractApiError } from '@core/services/api-error.util';
import {
  EmailTemplate,
  EmailTemplateRenderResponse,
  EmailTemplatesApiService,
} from '../../services/email-templates-api.service';


@Component({
  selector: 'app-email-template-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, ReactiveFormsModule],
  templateUrl: './template-picker.component.html',
})
export class EmailTemplatePickerComponent {
  private readonly api = inject(EmailTemplatesApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly contactId = input<string | null>(null);
  readonly leadId = input<string | null>(null);

  readonly templateSelected = output<EmailTemplateRenderResponse>();
  readonly errored = output<string>();

  protected readonly open = signal<boolean>(false);
  protected readonly templates = signal<EmailTemplate[]>([]);
  protected readonly loading = signal<boolean>(false);
  protected readonly rendering = signal<string | null>(null);

  protected readonly searchCtrl = new FormControl<string>('', {
    nonNullable: true,
  });

  protected readonly canPick = computed(() => this.contactId() !== null);

  constructor() {
    this.searchCtrl.valueChanges
      .pipe(
        debounceTime(200),
        distinctUntilChanged(),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((q) => this._load(q.trim()));
  }

  toggle(): void {
    if (!this.canPick()) return;
    const next = !this.open();
    this.open.set(next);
    if (next && this.templates().length === 0) {
      this._load('');
    }
  }

  close(): void {
    this.open.set(false);
  }

  /** Click anywhere outside the picker root closes the popover. The
   *  host listener checks the click target against the component's
   *  DOM subtree via `closest`. */
  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (!this.open()) return;
    const target = event.target as Element | null;
    if (target && target.closest('app-email-template-picker')) return;
    this.open.set(false);
  }

  pick(t: EmailTemplate): void {
    const contactId = this.contactId();
    if (!contactId || this.rendering() !== null) return;
    this.rendering.set(t.id);
    const leadId = this.leadId() ?? undefined;
    this.api
      .render(t.id, { contactId, leadId })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.rendering.set(null);
          this.open.set(false);
          this.templateSelected.emit(resp);
        },
        error: (err: HttpErrorResponse) => {
          this.rendering.set(null);
          this.errored.emit(extractApiError(err));
        },
      });
  }

  private _load(q: string): void {
    this.loading.set(true);
    this.api
      .list({ q: q || undefined, is_active: true, size: 30 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.templates.set(resp.items);
          this.loading.set(false);
        },
        error: () => {
          this.loading.set(false);
        },
      });
  }
}
