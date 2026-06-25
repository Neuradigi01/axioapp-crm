import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../../auth/auth.service';

import { ChannelChipComponent } from '../channel-chip.component';
import { TemplateReviewModalComponent } from '../review/template-review.modal';
import { TemplateStatusBadgeComponent } from '../template-status-badge.component';
import { TestSendModalComponent } from '../test-send/test-send.modal';
import {
  SmsDltMetadataPatch,
  TemplateChannel,
  TemplateCreatePayload,
  TemplateRead,
  TemplateUpdatePayload,
  TemplatesApiService,
} from '../templates-api.service';
import { VersionsDrawerComponent } from '../versions/versions-drawer.component';
import { EmailFormComponent, EmailFormGroup } from './email-form.component';
import { PreviewPaneComponent } from './preview-pane.component';
import { SmsFormComponent, SmsFormGroup } from './sms-form.component';
import { VariablePickerComponent } from './variable-picker.component';
import { WaFormComponent, WaFormGroup } from './wa-form.component';


/**
 * Template editor page — used for both `/new` and `/:id` routes.
 *
 * Owns:
 *   - The top-level "name + channel" form root.
 *   - The channel-specific sub-form (WA or Email today, others later).
 *   - The variable picker → focused-textarea routing.
 *   - The live preview pane.
 *   - Save / save-and-submit flows.
 *   - The 30s auto-save effect (only fires on already-saved drafts).
 *
 * Locked status: when the template's `internal_status` is in
 * (in_review, approved, published), the form controls are disabled +
 * a banner appears. The operator clicks "Move to draft" (visible to
 * reviewers via reject) which Step 8's review modal handles. v1 just
 * shows the banner — the unlock path lives in Step 8.
 */
type ChannelOption = '' | 'whatsapp' | 'email' | 'sms';

const LOCKED_STATUSES = new Set(['in_review', 'approved', 'published']);


@Component({
  selector: 'app-template-editor-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterLink,
    LucideAngularModule,
    ChannelChipComponent,
    TemplateStatusBadgeComponent,
    VariablePickerComponent,
    PreviewPaneComponent,
    WaFormComponent,
    EmailFormComponent,
    SmsFormComponent,
    TemplateReviewModalComponent,
    TestSendModalComponent,
    VersionsDrawerComponent,
  ],
  templateUrl: './template-editor.page.html',
})
export class TemplateEditorPageComponent {
  private readonly api = inject(TemplatesApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  // --- header form ----------------------------------------------------

  protected readonly headerForm = new FormGroup({
    name: new FormControl<string>('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(120)],
    }),
    channel: new FormControl<ChannelOption>('', {
      nonNullable: true,
      validators: [Validators.required],
    }),
  });

  // --- channel sub-forms (lazy-built on channel choice) ---------------

  protected readonly waForm = signal<WaFormGroup | null>(null);
  protected readonly emailForm = signal<EmailFormGroup | null>(null);
  protected readonly smsForm = signal<SmsFormGroup | null>(null);

  // --- loaded template (null for /new) --------------------------------

  protected readonly template = signal<TemplateRead | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly saveError = signal<string | null>(null);
  protected readonly toast = signal<string | null>(null);
  protected readonly saving = signal<boolean>(false);

  protected readonly channel = computed<TemplateChannel | null>(() => {
    const t = this.template();
    if (t) return t.channel;
    const c = this.headerForm.controls.channel.value;
    return c === '' ? null : (c as TemplateChannel);
  });

  protected readonly locked = computed(() => {
    const t = this.template();
    return t !== null && LOCKED_STATUSES.has(t.internal_status);
  });

  protected readonly canWrite = computed(() =>
    this.auth.hasPermission('templates.write'),
  );
  protected readonly canReview = computed(() =>
    this.auth.hasPermission('templates.review'),
  );
  protected readonly canPublish = computed(() =>
    this.auth.hasPermission('templates.publish'),
  );
  protected readonly canSubmitExternal = computed(() =>
    this.auth.hasPermission('templates.submit_external'),
  );

  // --- header-button visibility (Step 8 + Step 9) ---------------------

  protected readonly showSubmitButton = computed(() => {
    const t = this.template();
    return (
      t !== null &&
      t.internal_status === 'draft' &&
      this.canWrite() &&
      !this.locked()
    );
  });
  protected readonly showReviewButton = computed(() => {
    const t = this.template();
    return t !== null && t.internal_status === 'in_review' && this.canReview();
  });
  protected readonly showPublishButton = computed(() => {
    const t = this.template();
    return t !== null && t.internal_status === 'approved' && this.canPublish();
  });
  protected readonly showArchiveButton = computed(() => {
    const t = this.template();
    return (
      t !== null &&
      t.internal_status !== 'archived' &&
      this.canWrite()
    );
  });
  protected readonly showTestSendButton = computed(
    () => this.template() !== null,
  );
  protected readonly showVersionsButton = computed(
    () => this.template() !== null,
  );
  /** Step 9 — Submit-to-Meta is visible only on WhatsApp templates that
   *  are published (or approved internally) AND whose external status
   *  is either n_a (never submitted) or rejected (resubmission).
   *  Anything else (pending / already approved on Meta) hides it. */
  protected readonly showSubmitExternalButton = computed(() => {
    const t = this.template();
    if (t === null) return false;
    if (t.channel !== 'whatsapp') return false;
    if (!this.canSubmitExternal()) return false;
    const internalOk =
      t.internal_status === 'published' || t.internal_status === 'approved';
    const externalOk =
      t.external_status === 'n_a' || t.external_status === 'rejected';
    return internalOk && externalOk;
  });

  // --- modal / drawer state ------------------------------------------

  protected readonly reviewModalOpen = signal<boolean>(false);
  protected readonly testSendModalOpen = signal<boolean>(false);
  protected readonly versionsDrawerOpen = signal<boolean>(false);
  protected readonly transitioning = signal<string | null>(null);

  protected readonly currentBody = signal<string>('');
  protected readonly currentSubject = signal<string | null>(null);

  // The textarea / input the variable-picker click should insert into.
  private focusedField: HTMLTextAreaElement | HTMLInputElement | null = null;
  protected readonly trackFocus = (
    el: HTMLTextAreaElement | HTMLInputElement,
  ): void => {
    this.focusedField = el;
  };

  // --- auto-save scaffolding -----------------------------------------

  private autoSaveTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    // React to channel selection — build the matching sub-form if it
    // doesn't exist yet, clear the unused one.
    effect(() => {
      const channel = this.channel();
      if (channel === 'whatsapp' && this.waForm() === null) {
        this.waForm.set(WaFormComponent.build());
      }
      if (channel === 'email' && this.emailForm() === null) {
        this.emailForm.set(EmailFormComponent.build());
      }
      if (channel === 'sms' && this.smsForm() === null) {
        this.smsForm.set(SmsFormComponent.build());
      }
    });

    // Wire body / subject signals from whichever sub-form is active so
    // the preview pane updates as the operator types.
    effect((onCleanup) => {
      const channel = this.channel();
      if (channel === 'whatsapp') {
        const f = this.waForm();
        if (!f) return;
        const sub = f.controls.body_text.valueChanges
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe((v) => {
            this.currentBody.set(v ?? '');
            this.scheduleAutoSave();
          });
        this.currentBody.set(f.controls.body_text.value);
        this.currentSubject.set(null);
        onCleanup(() => sub.unsubscribe());
      } else if (channel === 'email') {
        const f = this.emailForm();
        if (!f) return;
        const subBody = f.controls.body_text.valueChanges
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe((v) => {
            this.currentBody.set(v ?? '');
            this.scheduleAutoSave();
          });
        const subSubject = f.controls.subject.valueChanges
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe((v) => {
            this.currentSubject.set(v ?? '');
            this.scheduleAutoSave();
          });
        this.currentBody.set(f.controls.body_text.value);
        this.currentSubject.set(f.controls.subject.value);
        onCleanup(() => {
          subBody.unsubscribe();
          subSubject.unsubscribe();
        });
      } else if (channel === 'sms') {
        const f = this.smsForm();
        if (!f) return;
        const subBody = f.controls.body_text.valueChanges
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe((v) => {
            this.currentBody.set(v ?? '');
            this.scheduleAutoSave();
          });
        // The DLT fields are saved together with body_text. Any
        // change schedules the auto-save so the operator doesn't
        // need to remember to click "Save draft" after editing IDs.
        const subDlt = f.valueChanges
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe(() => this.scheduleAutoSave());
        this.currentBody.set(f.controls.body_text.value);
        this.currentSubject.set(null);
        onCleanup(() => {
          subBody.unsubscribe();
          subDlt.unsubscribe();
        });
      }
    });

    // Load existing template when the route carries an `:id` (or stays
    // empty for the `/new` path).
    this.route.paramMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((params) => {
        const id = params.get('id');
        if (id) this.loadTemplate(id);
      });
  }

  // --- load / hydrate -------------------------------------------------

  private loadTemplate(id: string): void {
    this.loadError.set(null);
    this.api
      .get(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.template.set(row);
          this.headerForm.controls.name.setValue(row.name);
          this.headerForm.controls.channel.setValue(
            row.channel as ChannelOption,
          );
          // Channel-locked once saved.
          this.headerForm.controls.channel.disable({ emitEvent: false });
          if (row.channel === 'whatsapp') {
            const f = this.waForm() ?? WaFormComponent.build();
            f.patchValue({
              body_text: row.body_text,
              language: row.language,
            });
            this.waForm.set(f);
          } else if (row.channel === 'email') {
            const f = this.emailForm() ?? EmailFormComponent.build();
            f.patchValue({
              subject: row.subject ?? '',
              preview_text: row.preview_text ?? '',
              body_text: row.body_text,
            });
            this.emailForm.set(f);
          } else if (row.channel === 'sms') {
            const f = this.smsForm() ?? SmsFormComponent.build();
            f.patchValue({ body_text: row.body_text });
            this.smsForm.set(f);
            this.loadSmsDltMetadata(row.id);
          }
          if (this.locked()) {
            this.headerForm.disable({ emitEvent: false });
            this.waForm()?.disable({ emitEvent: false });
            this.emailForm()?.disable({ emitEvent: false });
            this.smsForm()?.disable({ emitEvent: false });
          }
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(
            extractApiError(err) ?? 'Could not load template.',
          );
        },
      });
  }

  private loadSmsDltMetadata(templateId: string): void {
    this.api
      .getSmsMetadata(templateId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (meta) => {
          const f = this.smsForm();
          if (!f) return;
          f.patchValue(
            {
              dlt_entity_id: meta.dlt_entity_id ?? '',
              dlt_template_id: meta.dlt_template_id ?? '',
              dlt_content_category: meta.dlt_content_category,
              dlt_header: meta.dlt_header ?? '',
              dlt_principal_entity_id: meta.dlt_principal_entity_id ?? '',
              dlt_template_status: meta.dlt_template_status,
            },
            { emitEvent: false },
          );
        },
        error: () => {
          // Non-fatal — the form falls back to its defaults (pending
          // / transactional) and the operator can still save body
          // text. A real error surface lives on the next save.
        },
      });
  }

  // --- variable insertion --------------------------------------------

  protected onInsertVariable(token: string): void {
    const el = this.focusedField;
    if (!el) {
      this.toast.set('Click into the field you want before picking a variable.');
      return;
    }
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    const before = el.value.slice(0, start);
    const after = el.value.slice(end);
    const next = `${before}${token}${after}`;
    el.value = next;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    const caret = start + token.length;
    el.setSelectionRange(caret, caret);
    el.focus();
  }

  // --- save / save & submit ------------------------------------------

  private buildPayload(): TemplateCreatePayload | TemplateUpdatePayload {
    const channel = this.channel();
    if (channel === 'whatsapp') {
      const f = this.waForm();
      const base = {
        name: this.headerForm.controls.name.value,
        channel: 'whatsapp' as const,
        language: f?.controls.language.value ?? 'en',
        body_text: f?.controls.body_text.value ?? '',
      };
      return base;
    }
    if (channel === 'sms') {
      const f = this.smsForm();
      return {
        name: this.headerForm.controls.name.value,
        channel: 'sms' as const,
        language: 'en',
        body_text: f?.controls.body_text.value ?? '',
      };
    }
    // Email.
    const f = this.emailForm();
    return {
      name: this.headerForm.controls.name.value,
      channel: 'email' as const,
      language: 'en',
      body_text: f?.controls.body_text.value ?? '',
      subject: f?.controls.subject.value ?? '',
      preview_text: f?.controls.preview_text.value || null,
    };
  }

  private buildSmsDltPatch(): SmsDltMetadataPatch | null {
    const f = this.smsForm();
    if (!f) return null;
    const v = f.getRawValue();
    return {
      dlt_entity_id: v.dlt_entity_id || null,
      dlt_template_id: v.dlt_template_id || null,
      dlt_content_category: v.dlt_content_category,
      dlt_header: v.dlt_header || null,
      dlt_principal_entity_id: v.dlt_principal_entity_id || null,
      dlt_template_status: v.dlt_template_status,
    };
  }

  protected save(): void {
    if (this.locked()) return;
    if (!this.canWrite()) return;
    const channel = this.channel();
    if (!channel) {
      this.saveError.set('Pick a channel before saving.');
      return;
    }
    const subForm =
      channel === 'whatsapp'
        ? this.waForm()
        : channel === 'sms'
          ? this.smsForm()
          : this.emailForm();
    if (this.headerForm.invalid || subForm?.invalid) {
      this.headerForm.markAllAsTouched();
      subForm?.markAllAsTouched();
      this.saveError.set('Fix the highlighted fields and try again.');
      return;
    }
    this.saveError.set(null);
    this.saving.set(true);
    const existing = this.template();
    const payload = this.buildPayload();

    const obs = existing
      ? this.api.update(existing.id, payload as TemplateUpdatePayload)
      : this.api.create(payload as TemplateCreatePayload);

    obs.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (row) => {
        if (row.channel === 'sms') {
          const dltPatch = this.buildSmsDltPatch();
          if (dltPatch) {
            this.api
              .patchSmsMetadata(row.id, dltPatch)
              .pipe(takeUntilDestroyed(this.destroyRef))
              .subscribe({
                next: () => this.finishSave(row, !existing),
                error: (err: HttpErrorResponse) => {
                  // Central row saved; only the DLT patch failed. The
                  // toast nudges the operator to retry so they don't
                  // think the whole save was lost.
                  this.saving.set(false);
                  this.template.set(row);
                  this.saveError.set(
                    extractApiError(err) ??
                      'Saved the body, but DLT metadata failed to save.',
                  );
                },
              });
            return;
          }
        }
        this.finishSave(row, !existing);
      },
      error: (err: HttpErrorResponse) => {
        this.saving.set(false);
        this.saveError.set(extractApiError(err) ?? 'Could not save template.');
      },
    });
  }

  private finishSave(row: TemplateRead, isNew: boolean): void {
    this.saving.set(false);
    this.template.set(row);
    this.toast.set(`Saved · v${row.current_version}`);
    if (isNew) {
      void this.router.navigate(['/user/templates', row.id], {
        replaceUrl: true,
      });
    }
  }

  private scheduleAutoSave(): void {
    if (!this.template() || this.locked() || !this.canWrite()) return;
    if (this.autoSaveTimer) clearTimeout(this.autoSaveTimer);
    this.autoSaveTimer = setTimeout(() => {
      this.save();
    }, 30_000);
  }

  protected dismissToast(): void {
    this.toast.set(null);
  }

  // --- workflow header actions (Step 8) ------------------------------

  protected submitForReview(): void {
    const t = this.template();
    if (!t || this.transitioning()) return;
    this.transitioning.set('submit');
    this.api
      .submit(t.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => this.applyTransition(row, 'Submitted for review'),
        error: (err: HttpErrorResponse) => this.applyTransitionError(err),
      });
  }

  protected publishTemplate(): void {
    const t = this.template();
    if (!t || this.transitioning()) return;
    this.transitioning.set('publish');
    this.api
      .publish(t.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => this.applyTransition(row, 'Published'),
        error: (err: HttpErrorResponse) => this.applyTransitionError(err),
      });
  }

  protected archiveTemplate(): void {
    const t = this.template();
    if (!t || this.transitioning()) return;
    this.transitioning.set('archive');
    this.api
      .archiveViaWorkflow(t.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => this.applyTransition(row, 'Archived'),
        error: (err: HttpErrorResponse) => this.applyTransitionError(err),
      });
  }

  protected submitToMeta(): void {
    const t = this.template();
    if (!t || this.transitioning()) return;
    this.transitioning.set('submit_external');
    this.api
      .submitExternal(t.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => this.applyTransition(row, 'Submitted to Meta'),
        error: (err: HttpErrorResponse) => this.applyTransitionError(err),
      });
  }

  private applyTransition(row: TemplateRead, message: string): void {
    this.transitioning.set(null);
    this.template.set(row);
    if (LOCKED_STATUSES.has(row.internal_status)) {
      this.headerForm.disable({ emitEvent: false });
      this.waForm()?.disable({ emitEvent: false });
      this.emailForm()?.disable({ emitEvent: false });
      this.smsForm()?.disable({ emitEvent: false });
    } else {
      // Workflow may have moved a previously-locked template back to
      // draft (reject / request-changes) — re-enable the form so
      // editing resumes. Channel stays locked once a template exists.
      this.headerForm.enable({ emitEvent: false });
      this.headerForm.controls.channel.disable({ emitEvent: false });
      this.waForm()?.enable({ emitEvent: false });
      this.emailForm()?.enable({ emitEvent: false });
      this.smsForm()?.enable({ emitEvent: false });
    }
    this.toast.set(message);
  }

  private applyTransitionError(err: HttpErrorResponse): void {
    this.transitioning.set(null);
    this.saveError.set(
      extractApiError(err) ?? 'Could not complete the action.',
    );
  }

  // --- modal / drawer triggers ---------------------------------------

  protected openReviewModal(): void {
    this.reviewModalOpen.set(true);
  }
  protected closeReviewModal(): void {
    this.reviewModalOpen.set(false);
  }
  protected onReviewSucceeded(row: TemplateRead): void {
    this.applyTransition(row, `Marked ${row.internal_status}`);
  }

  protected openTestSendModal(): void {
    this.testSendModalOpen.set(true);
  }
  protected closeTestSendModal(): void {
    this.testSendModalOpen.set(false);
  }

  protected openVersionsDrawer(): void {
    this.versionsDrawerOpen.set(true);
  }
  protected closeVersionsDrawer(): void {
    this.versionsDrawerOpen.set(false);
  }
  protected onRestoredFromVersion(row: TemplateRead): void {
    this.applyTransition(row, `Restored — now at v${row.current_version}`);
    if (row.channel === 'whatsapp') {
      this.waForm()?.patchValue(
        { body_text: row.body_text, language: row.language },
        { emitEvent: false },
      );
    } else if (row.channel === 'email') {
      this.emailForm()?.patchValue(
        {
          subject: row.subject ?? '',
          preview_text: row.preview_text ?? '',
          body_text: row.body_text,
        },
        { emitEvent: false },
      );
    } else if (row.channel === 'sms') {
      this.smsForm()?.patchValue(
        { body_text: row.body_text },
        { emitEvent: false },
      );
    }
    this.currentBody.set(row.body_text);
    this.currentSubject.set(row.subject ?? null);
  }
}
