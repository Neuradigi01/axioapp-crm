/**
 * Blocklist tab (tasks/email-quarantine-filters Step 5).
 *
 * Manages the ``tbl_email_filter_rules`` allow/block rules.
 * Owner+Admin only. Cap of 500 rules per org (enforced server-side).
 */
import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  OnInit,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import {
  CreateFilterRuleRequest,
  FilterRule,
  MatchKind,
  QuarantineService,
  RuleType,
} from './quarantine.service';

@Component({
  selector: 'app-blocklist-tab',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './blocklist-tab.component.html',
})
export class BlocklistTabComponent implements OnInit {
  private readonly svc = inject(QuarantineService);

  readonly rules = signal<FilterRule[]>([]);
  readonly loading = signal<boolean>(false);
  readonly errorMessage = signal<string | null>(null);
  readonly filterKind = signal<RuleType | 'all'>('all');
  readonly modalOpen = signal<boolean>(false);

  // Form state
  readonly draftRuleType = signal<RuleType>('block');
  readonly draftMatchKind = signal<MatchKind>('email_address');
  readonly draftMatchValue = signal<string>('');
  readonly draftLabel = signal<string>('');
  readonly formError = signal<string | null>(null);
  readonly submitting = signal<boolean>(false);

  readonly filteredRules = computed(() => {
    const kind = this.filterKind();
    const all = this.rules();
    if (kind === 'all') return all;
    return all.filter((r) => r.rule_type === kind);
  });

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.errorMessage.set(null);
    this.svc.listRules().subscribe({
      next: (rows) => {
        this.rules.set(rows);
        this.loading.set(false);
      },
      error: (err) => {
        this.errorMessage.set(err?.error?.detail ?? 'Failed to load rules');
        this.loading.set(false);
      },
    });
  }

  openAddModal(): void {
    this.draftRuleType.set('block');
    this.draftMatchKind.set('email_address');
    this.draftMatchValue.set('');
    this.draftLabel.set('');
    this.formError.set(null);
    this.modalOpen.set(true);
  }

  closeModal(): void {
    this.modalOpen.set(false);
  }

  submit(): void {
    const value = this.draftMatchValue().trim();
    if (!value) {
      this.formError.set('Match value is required');
      return;
    }
    const payload: CreateFilterRuleRequest = {
      rule_type: this.draftRuleType(),
      match_kind: this.draftMatchKind(),
      match_value: value,
      label: this.draftLabel().trim() || null,
    };
    this.submitting.set(true);
    this.svc.createRule(payload).subscribe({
      next: () => {
        this.submitting.set(false);
        this.modalOpen.set(false);
        this.load();
      },
      error: (err) => {
        this.submitting.set(false);
        this.formError.set(err?.error?.detail ?? 'Failed to create rule');
      },
    });
  }

  deleteRule(rule: FilterRule): void {
    const target =
      rule.match_kind === 'contact_flag' ? `flag "${rule.match_value}"` : rule.match_value;
    if (!confirm(`Delete rule for ${target}?`)) return;
    this.svc.deleteRule(rule.id).subscribe({
      next: () => this.load(),
      error: (err) => this.errorMessage.set(err?.error?.detail ?? 'Failed to delete rule'),
    });
  }

  matchKindLabel(kind: MatchKind): string {
    switch (kind) {
      case 'email_address':
        return 'Address';
      case 'email_domain':
        return 'Domain';
      case 'contact_flag':
        return 'Contact flag';
    }
  }
}
