/**
 * Template editor — used by both `/new` and `/:id/edit` routes.
 *
 * Layout:
 *   - Left column: name + subject + body_html textarea (monospace,
 *     plain HTML for v1; WYSIWYG is v2).
 *   - Right column: Variables sidebar (categorised) — click a row
 *     to splice `{{ <path> }}` at the active textarea's caret.
 *   - Bottom: Preview tab — pick a contact via typeahead, POST to
 *     `/render`, show subject + body_html in a sandboxed iframe.
 *
 * State signals:
 *   - `loading` — initial GET when in edit mode
 *   - `submitting` — POST/PATCH in flight
 *   - `preview` — current rendered output (null until first render)
 *   - `previewError` — 400 from /render (lists missing variables)
 *   - `view` — 'edit' | 'preview'; preview tab requires `template().
 *     id` (must be saved first OR test-rendered against the in-form
 *     content via a future enhancement; v1: save first).
 *
 * `previewIframeSrcDoc` is wrapped with `DomSanitizer.bypassSecurityTrustHtml`
 * because we're INSERTING server-rendered HTML into an iframe via
 * `srcdoc`. The iframe carries `sandbox="allow-same-origin"` minus
 * `allow-scripts` so any unexpected `<script>` in the rendered output
 * is neutered.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  ViewChild,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import {
  FormBuilder,
  FormControl,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { Subject, debounceTime, distinctUntilChanged, of, switchMap } from 'rxjs';

import { extractApiError } from '@core/services/api-error.util';
import {
  ContactListItem,
  ContactsApiService,
} from '../../contacts/contacts-api.service';
import {
  EmailTemplate,
  EmailTemplateRenderResponse,
  EmailTemplatesApiService,
  VariableRegistryEntry,
} from '../../services/email-templates-api.service';


interface EditForm {
  name: FormControl<string>;
  subject: FormControl<string>;
  body_html: FormControl<string>;
  body_text: FormControl<string>;
  is_active: FormControl<boolean>;
}


@Component({
  selector: 'app-email-template-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, ReactiveFormsModule, RouterLink],
  templateUrl: './template-editor.component.html',
})
export class EmailTemplateEditorComponent implements OnInit {
  private readonly api = inject(EmailTemplatesApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly destroyRef = inject(DestroyRef);

  /** Template id when editing; null for /new. */
  readonly templateId = input<string | null>(null);

  protected readonly isEdit = computed(() => this.templateId() !== null);

  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly submitting = signal<boolean>(false);
  protected readonly submitError = signal<string | null>(null);

  protected readonly view = signal<'edit' | 'preview'>('edit');

  protected readonly variables = signal<VariableRegistryEntry[]>([]);
  protected readonly variablesLoading = signal<boolean>(false);

  /** Grouped variables by category for sidebar rendering. */
  protected readonly variablesByCategory = computed(() => {
    const groups = new Map<string, VariableRegistryEntry[]>();
    for (const v of this.variables()) {
      const list = groups.get(v.category) ?? [];
      list.push(v);
      groups.set(v.category, list);
    }
    return Array.from(groups.entries()).map(([category, items]) => ({
      category,
      items,
    }));
  });

  // --- Preview state -----------------------------------------------

  protected readonly preview = signal<EmailTemplateRenderResponse | null>(
    null,
  );
  protected readonly previewing = signal<boolean>(false);
  protected readonly previewError = signal<string | null>(null);
  protected readonly previewContact = signal<ContactListItem | null>(null);
  protected readonly contactSearch = new FormControl<string>('', {
    nonNullable: true,
  });
  protected readonly contactResults = signal<ContactListItem[]>([]);
  protected readonly contactSearchLoading = signal<boolean>(false);
  private readonly contactSearch$ = new Subject<string>();

  protected readonly previewBodyHtml = computed<SafeHtml | null>(() => {
    const p = this.preview();
    if (!p) return null;
    return this.sanitizer.bypassSecurityTrustHtml(p.body_html);
  });

  // --- Form --------------------------------------------------------

  protected readonly form = this.fb.group<EditForm>({
    name: this.fb.nonNullable.control('', [
      Validators.required,
      Validators.maxLength(255),
    ]),
    subject: this.fb.nonNullable.control('', [
      Validators.required,
      Validators.maxLength(998),
    ]),
    body_html: this.fb.nonNullable.control('', [Validators.required]),
    body_text: this.fb.nonNullable.control(''),
    is_active: this.fb.nonNullable.control(true),
  });

  /** Last-focused textarea so the variable-picker knows where to
   *  splice. Updated by the body / subject focus handlers. */
  protected lastFocusedField: 'subject' | 'body_html' = 'body_html';

  ngOnInit(): void {
    this._loadVariables();
    const id = this.templateId();
    if (id !== null) this._loadTemplate(id);

    this.contactSearch.valueChanges
      .pipe(
        debounceTime(250),
        distinctUntilChanged(),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((q) => this.contactSearch$.next(q));

    this.contactSearch$
      .pipe(
        switchMap((q) => {
          if (!q || q.length < 2) {
            this.contactResults.set([]);
            return of(null);
          }
          this.contactSearchLoading.set(true);
          return this.contactsApi.list({ q, page: 1, size: 8 });
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (resp) => {
          this.contactSearchLoading.set(false);
          if (resp) this.contactResults.set(resp.items);
        },
        error: () => {
          this.contactSearchLoading.set(false);
          this.contactResults.set([]);
        },
      });
  }

  // --- Variable insertion ------------------------------------------

  protected onSubjectFocus(): void {
    this.lastFocusedField = 'subject';
  }

  protected onBodyFocus(): void {
    this.lastFocusedField = 'body_html';
  }

  protected insertVariable(entry: VariableRegistryEntry): void {
    const placeholder = `{{ ${entry.path} }}`;
    const fieldName = this.lastFocusedField;
    const control =
      fieldName === 'subject'
        ? this.form.controls.subject
        : this.form.controls.body_html;
    // Native textarea + input both expose `selectionStart`/`End`.
    const el = document.querySelector<HTMLTextAreaElement | HTMLInputElement>(
      `[data-tpl-field="${fieldName}"]`,
    );
    const current = control.value ?? '';
    if (!el) {
      control.setValue(current + placeholder);
      return;
    }
    const start = el.selectionStart ?? current.length;
    const end = el.selectionEnd ?? current.length;
    const next = current.slice(0, start) + placeholder + current.slice(end);
    control.setValue(next);
    // Restore caret after the inserted placeholder.
    queueMicrotask(() => {
      el.focus();
      const caret = start + placeholder.length;
      el.setSelectionRange(caret, caret);
    });
  }

  // --- Preview -----------------------------------------------------

  protected switchToPreview(): void {
    this.previewError.set(null);
    this.view.set('preview');
    if (this.previewContact()) {
      this._runPreview();
    }
  }

  protected switchToEdit(): void {
    this.view.set('edit');
  }

  protected pickContact(contact: ContactListItem): void {
    this.previewContact.set(contact);
    this.contactSearch.setValue(contact.full_name, { emitEvent: false });
    this.contactResults.set([]);
    this._runPreview();
  }

  protected clearContact(): void {
    this.previewContact.set(null);
    this.preview.set(null);
    this.contactSearch.setValue('', { emitEvent: false });
  }

  private _runPreview(): void {
    const contact = this.previewContact();
    const id = this.templateId();
    if (!contact || !id) {
      this.previewError.set(
        'Save the template first, then pick a contact to preview against.',
      );
      return;
    }
    this.previewing.set(true);
    this.previewError.set(null);
    this.api
      .render(id, { contactId: contact.id })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.preview.set(resp);
          this.previewing.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.previewing.set(false);
          this.previewError.set(extractApiError(err));
          this.preview.set(null);
        },
      });
  }

  // --- Save --------------------------------------------------------

  protected save(): void {
    if (this.submitting()) return;
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const id = this.templateId();
    const payload = this.form.getRawValue();
    this.submitting.set(true);
    this.submitError.set(null);
    const request$ =
      id === null
        ? this.api.create(payload)
        : this.api.update(id, payload);
    request$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (saved) => {
          this.submitting.set(false);
          // Navigate to the edit URL so a refresh stays here.
          this.router.navigate([
            '/user/settings/email-templates',
            saved.id,
            'edit',
          ]);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(extractApiError(err));
        },
      });
  }

  // --- Loaders -----------------------------------------------------

  private _loadVariables(): void {
    this.variablesLoading.set(true);
    this.api
      .variables()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.variables.set(rows);
          this.variablesLoading.set(false);
        },
        error: () => {
          this.variablesLoading.set(false);
        },
      });
  }

  private _loadTemplate(id: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .get(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.form.patchValue({
            name: row.name,
            subject: row.subject,
            body_html: row.body_html,
            body_text: row.body_text,
            is_active: row.is_active,
          });
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err));
        },
      });
  }
}
