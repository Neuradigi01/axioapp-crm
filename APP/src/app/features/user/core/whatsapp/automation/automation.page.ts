import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../../auth/auth.service';

import { KeywordRuleEditorComponent } from './keyword-rule-editor.component';
import {
  KeywordRule,
  RuleTestResponse,
  WhatsAppAutomationApiService,
} from './whatsapp-automation-api.service';

type Mode = 'list' | 'create' | 'edit';


/**
 * WhatsApp Automation page (whatsapp-platform-upgrade Step 17).
 *
 * Single-route owner for the keyword-rule surface. List view +
 * inline editor + dry-run test panel — all in one page so the
 * operator stays oriented while authoring rules.
 *
 * Future Step 18 (auto-assignment) + Step 19 (AI agent settings)
 * will add tabs to this same page.
 */
@Component({
  selector: 'app-whatsapp-automation-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FormsModule,
    LucideAngularModule,
    KeywordRuleEditorComponent,
  ],
  templateUrl: './automation.page.html',
})
export class WhatsAppAutomationPageComponent {
  private readonly api = inject(WhatsAppAutomationApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly rules = signal<KeywordRule[]>([]);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly toast = signal<string | null>(null);

  protected readonly mode = signal<Mode>('list');
  protected readonly editingRule = signal<KeywordRule | null>(null);

  // Dry-run test panel
  protected readonly testText = signal<string>('');
  protected readonly testRunning = signal<boolean>(false);
  protected readonly testResult = signal<RuleTestResponse | null>(null);
  protected readonly testError = signal<string | null>(null);

  protected readonly canManage = computed(() =>
    this.auth.hasPermission('whatsapp.automation.manage'),
  );

  constructor() {
    this.reload();
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.rules.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.rules.set([]);
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load automation rules.',
          );
        },
      });
  }

  // --- mode switching --------------------------------------------

  protected openCreate(): void {
    if (!this.canManage()) return;
    this.editingRule.set(null);
    this.mode.set('create');
  }

  protected openEdit(rule: KeywordRule): void {
    if (!this.canManage()) return;
    this.editingRule.set(rule);
    this.mode.set('edit');
  }

  protected closeEditor(): void {
    this.editingRule.set(null);
    this.mode.set('list');
  }

  protected onSaved(rule: KeywordRule): void {
    this.toast.set(
      this.mode() === 'create' ? 'Rule created.' : 'Rule saved.',
    );
    this.closeEditor();
    this.reload();
  }

  // --- list actions ----------------------------------------------

  protected toggleEnabled(rule: KeywordRule): void {
    if (!this.canManage()) return;
    this.api
      .update(rule.id, {
        name: rule.name,
        keywords: rule.keywords,
        match_type: rule.match_type,
        enabled: !rule.enabled,
        priority: rule.priority,
        actions: rule.actions.map((a) => ({
          action_type: a.action_type,
          action_config: a.action_config,
          position: a.position,
        })),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.rules.update((arr) =>
            arr.map((r) => (r.id === updated.id ? updated : r)),
          );
        },
        error: (err: HttpErrorResponse) => {
          this.toast.set(
            extractApiError(err) ?? 'Could not toggle the rule.',
          );
        },
      });
  }

  protected confirmDelete(rule: KeywordRule): void {
    if (!this.canManage()) return;
    if (!confirm(`Delete rule "${rule.name}"?`)) return;
    this.api
      .delete(rule.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.rules.update((arr) =>
            arr.filter((r) => r.id !== rule.id),
          );
          this.toast.set('Rule deleted.');
        },
        error: (err: HttpErrorResponse) => {
          this.toast.set(
            extractApiError(err) ?? 'Could not delete the rule.',
          );
        },
      });
  }

  /** Move a rule one step up in priority (reorder helper). The
   *  backend's `reorder` endpoint reassigns priorities based on the
   *  resulting list order. */
  protected moveUp(idx: number): void {
    if (idx === 0) return;
    const next = [...this.rules()];
    [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
    this.applyReorder(next);
  }

  protected moveDown(idx: number): void {
    const current = this.rules();
    if (idx >= current.length - 1) return;
    const next = [...current];
    [next[idx], next[idx + 1]] = [next[idx + 1], next[idx]];
    this.applyReorder(next);
  }

  private applyReorder(ordered: KeywordRule[]): void {
    this.rules.set(ordered); // optimistic
    this.api
      .reorder(ordered.map((r) => r.id))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.rules.set(rows),
        error: (err: HttpErrorResponse) => {
          this.toast.set(
            extractApiError(err) ?? 'Could not reorder rules.',
          );
          // Roll back by re-fetching.
          this.reload();
        },
      });
  }

  // --- dry run ---------------------------------------------------

  protected runTest(): void {
    const text = this.testText().trim();
    if (!text) return;
    this.testRunning.set(true);
    this.testError.set(null);
    this.testResult.set(null);
    this.api
      .test(text)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.testResult.set(result);
          this.testRunning.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.testRunning.set(false);
          this.testError.set(
            extractApiError(err) ?? 'Could not run the test.',
          );
        },
      });
  }

  protected dismissToast(): void {
    this.toast.set(null);
  }
}
