import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';

import { ActivityTimelineComponent } from '../activities/activity-timeline.component';
import { AddNoteComponent } from '../activities/add-note.component';
import { Activity } from '../activities/activities-api.service';
import { TasksPanelComponent } from '../tasks/tasks-panel.component';
import { FieldDef } from '../shared/dynamic-form/types';
import {
  Contact,
  ContactCreate,
  ContactUpdate,
  ContactsApiService,
} from './contacts-api.service';
import { ContactFormModalComponent } from './contact-form-modal.component';

type DetailTab = 'overview' | 'activities' | 'notes' | 'tasks';

const TABS: ReadonlyArray<{ id: DetailTab; label: string; placeholderStep: string | null }> = [
  { id: 'overview', label: 'Overview', placeholderStep: null },
  { id: 'activities', label: 'Activities', placeholderStep: null },
  { id: 'notes', label: 'Notes', placeholderStep: 'later' },
  { id: 'tasks', label: 'Tasks', placeholderStep: null },
];

@Component({
  selector: 'app-contact-detail-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    LucideAngularModule,
    ContactFormModalComponent,
    ActivityTimelineComponent,
    AddNoteComponent,
    TasksPanelComponent,
  ],
  templateUrl: './contact-detail.page.html',
})
export class ContactDetailPageComponent implements OnInit {
  private readonly api = inject(ContactsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  readonly contact = signal<Contact | null>(null);
  readonly fields = signal<FieldDef[]>([]);
  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);

  readonly tabs = TABS;
  readonly activeTab = signal<DetailTab>('overview');

  /** Live handle on the timeline so add-note can prepend without a refetch. */
  protected readonly timeline = viewChild(ActivityTimelineComponent);

  /** Modal state: null = closed, Contact = edit. (No create from detail.) */
  readonly editingContact = signal<Contact | null>(null);
  readonly modalOpen = computed(() => this.editingContact() !== null);
  readonly submitting = signal(false);
  readonly formError = signal<string | null>(null);

  protected onNoteCreated(activity: Activity): void {
    this.timeline()?.prepend(activity);
  }

  readonly customFields = computed(() => {
    const c = this.contact();
    if (c === null) return [] as { label: string; value: string }[];
    const data = c.custom_data ?? {};
    return this.fields().map((def) => ({
      label: def.field_label,
      value: this.formatValue(def, data[def.field_key]),
    }));
  });

  readonly placeholderForActiveTab = computed<string | null>(() => {
    const tab = TABS.find((t) => t.id === this.activeTab());
    return tab?.placeholderStep ?? null;
  });

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (!id) {
      this.loadError.set('Contact id missing in URL.');
      this.loading.set(false);
      return;
    }
    this.loadContact(id);
    this.loadFields();
  }

  protected setTab(tab: DetailTab): void {
    this.activeTab.set(tab);
  }

  protected initials(name: string): string {
    return name
      .split(/\s+/)
      .filter((p) => p.length > 0)
      .slice(0, 2)
      .map((p) => p[0]!.toUpperCase())
      .join('');
  }

  protected openEdit(): void {
    const c = this.contact();
    if (c) this.editingContact.set(c);
  }

  protected closeModal(): void {
    this.editingContact.set(null);
    this.formError.set(null);
    this.submitting.set(false);
  }

  protected onSave(event: { create?: ContactCreate; update?: ContactUpdate }): void {
    const c = this.contact();
    if (!event.update || !c) return;
    this.submitting.set(true);
    this.formError.set(null);
    this.api
      .update(c.id, event.update)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.contact.set(updated);
          this.submitting.set(false);
          this.closeModal();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.formError.set(this.extractError(err) ?? 'Could not save contact.');
        },
      });
  }

  protected onDelete(): void {
    const c = this.contact();
    if (!c) return;
    const ok = window.confirm(
      `Delete contact "${c.full_name}"? This cannot be undone.`,
    );
    if (!ok) return;
    this.api
      .delete(c.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.router.navigate(['/user/contacts']),
        error: (err: HttpErrorResponse) => {
          this.loadError.set(this.extractError(err) ?? 'Could not delete contact.');
        },
      });
  }

  private loadContact(id: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .get(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (c) => {
          this.contact.set(c);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(this.extractError(err) ?? 'Could not load contact.');
          this.loading.set(false);
        },
      });
  }

  private loadFields(): void {
    this.api
      .renderFields()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (defs) => this.fields.set(defs),
        // Custom-field defs are nice-to-have; a failure here doesn't
        // block the standard fields from rendering. We silently skip
        // the Custom block instead of surfacing an error.
        error: () => this.fields.set([]),
      });
  }

  private formatValue(def: FieldDef, value: unknown): string {
    if (value === null || value === undefined || value === '') return '—';
    if (Array.isArray(value)) return value.length === 0 ? '—' : value.join(', ');
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    if (def.field_type === 'currency' && typeof value === 'number') {
      return new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency: 'INR',
        maximumFractionDigits: 2,
      }).format(value);
    }
    return String(value);
  }

  private extractError(err: HttpErrorResponse): string | null {
    const body = err?.error;
    if (typeof body === 'string') return body;
    if (body && typeof body === 'object') {
      const candidate =
        (body as { message?: string; detail?: unknown }).message
        ?? (body as { detail?: unknown }).detail;
      if (typeof candidate === 'string') return candidate;
    }
    return null;
  }
}
