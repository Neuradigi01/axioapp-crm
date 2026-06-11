/**
 * Settings → Email Templates list tab.
 *
 * Shows the org's saved templates with a debounced name filter; an
 * empty state with a Create CTA; and per-row Edit / Delete actions.
 *
 * Permission model:
 *   - Everyone with `email.read` (every role per Step 6 grants) sees
 *     the list — templates are shared so anyone composing can use
 *     them.
 *   - Only callers with `email.templates.manage` (Owner / Admin /
 *     Sales Manager) see Edit + Delete. The backend enforces 403 on
 *     write paths regardless of the UI gate.
 */
import { HttpErrorResponse } from '@angular/common/http';
import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../../auth/auth.service';
import {
  EmailTemplate,
  EmailTemplatesApiService,
} from '../../services/email-templates-api.service';


@Component({
  selector: 'app-email-templates-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DatePipe,
    LucideAngularModule,
    ReactiveFormsModule,
    RouterLink,
  ],
  templateUrl: './template-list.component.html',
})
export class EmailTemplatesListComponent implements OnInit {
  private readonly api = inject(EmailTemplatesApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly templates = signal<EmailTemplate[] | null>(null);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly inlineError = signal<string | null>(null);

  protected readonly deleting = signal<string | null>(null);
  protected readonly confirmDelete = signal<EmailTemplate | null>(null);

  protected readonly canManage = computed(() =>
    this.auth.hasPermission('email.templates.manage'),
  );

  protected readonly searchCtrl = new FormControl<string>('', {
    nonNullable: true,
  });

  protected readonly emptyState = computed(
    () => (this.templates()?.length ?? 0) === 0,
  );

  ngOnInit(): void {
    this._load('');
    this.searchCtrl.valueChanges
      .pipe(
        debounceTime(250),
        distinctUntilChanged(),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((value) => this._load(value.trim()));
  }

  refresh(): void {
    this._load(this.searchCtrl.value.trim());
  }

  openCreate(): void {
    this.router.navigate([
      '/user/settings/email-templates/new',
    ]);
  }

  openDelete(t: EmailTemplate): void {
    this.inlineError.set(null);
    this.confirmDelete.set(t);
  }

  cancelDelete(): void {
    if (this.deleting() !== null) return;
    this.confirmDelete.set(null);
  }

  confirmDeleteAction(): void {
    const target = this.confirmDelete();
    if (!target || this.deleting() !== null) return;
    this.deleting.set(target.id);
    this.api
      .delete(target.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.deleting.set(null);
          this.confirmDelete.set(null);
          this.refresh();
        },
        error: (err: HttpErrorResponse) => {
          this.deleting.set(null);
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  private _load(q: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list({ q: q || undefined })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.templates.set(resp.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(extractApiError(err));
        },
      });
  }
}
