import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';

/**
 * Step 29 — A/B test section on the campaign create modal.
 *
 * Pure-presentation component: the parent (`create-campaign-modal`)
 * owns the FormGroup + supplies the template id list; this block
 * just renders the inputs that bind into the form's A/B fields.
 *
 * Visible only when the parent's `is_ab_test` control is true —
 * the parent wraps this component in an `@if` so the inputs aren't
 * mounted (and thus required-validated) for single-template
 * campaigns.
 */
@Component({
  selector: 'app-ab-test-section',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, ReactiveFormsModule],
  template: `
    <div [formGroup]="form()" class="rounded-md border border-subtle bg-surface-2 p-3 text-xs">
      <p class="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
        A/B test configuration
      </p>
      <p class="mb-3 text-[11px] text-muted">
        Split your audience between two templates. After the hold-back window, the winner is
        auto-selected by the metric you choose — minimum 50 recipients to keep the result
        statistically meaningful.
      </p>

      <div class="mb-2 grid grid-cols-2 gap-2">
        <label>
          <span class="mb-1 block font-medium text-default"> Variant A template </span>
          <select
            formControlName="variant_a_template_id"
            class="w-full rounded-md border border-subtle bg-surface px-2.5 py-1.5"
          >
            <option [ngValue]="null">— Pick template A —</option>
            @for (t of templates(); track t.id) {
              <option [ngValue]="t.id">{{ t.name }}</option>
            }
          </select>
        </label>
        <label>
          <span class="mb-1 block font-medium text-default"> Variant B template </span>
          <select
            formControlName="variant_b_template_id"
            class="w-full rounded-md border border-subtle bg-surface px-2.5 py-1.5"
          >
            <option [ngValue]="null">— Pick template B —</option>
            @for (t of templates(); track t.id) {
              <option [ngValue]="t.id">{{ t.name }}</option>
            }
          </select>
        </label>
      </div>

      <label class="mb-2 block">
        <span class="mb-1 block font-medium text-default">
          Split ratio — % of audience that gets variant A ({{
            form().controls['split_ratio'].value
          }}%)
        </span>
        <input
          type="range"
          min="10"
          max="90"
          step="5"
          formControlName="split_ratio"
          class="w-full"
        />
        <span class="mt-1 block text-[10px] text-muted">
          Extremes (&lt; 10% or &gt; 90%) produce flaky winners on small audiences — capped at
          10–90%.
        </span>
      </label>

      <div class="grid grid-cols-2 gap-2">
        <label>
          <span class="mb-1 block font-medium text-default"> Winner metric </span>
          <select
            formControlName="winner_metric"
            class="w-full rounded-md border border-subtle bg-surface px-2.5 py-1.5"
          >
            <option [ngValue]="null">— Pick a metric —</option>
            <option value="reply_rate">Reply rate</option>
            <option value="read_rate">Read rate</option>
            <option value="click_rate">Click rate (interactive)</option>
          </select>
        </label>
        <label>
          <span class="mb-1 block font-medium text-default"> Hold-back window </span>
          <select
            formControlName="winner_holdback_hours"
            class="w-full rounded-md border border-subtle bg-surface px-2.5 py-1.5"
          >
            <option [ngValue]="6">6 hours</option>
            <option [ngValue]="12">12 hours</option>
            <option [ngValue]="24">24 hours (default)</option>
            <option [ngValue]="48">48 hours</option>
            <option [ngValue]="72">3 days</option>
            <option [ngValue]="168">1 week</option>
          </select>
        </label>
      </div>
    </div>
  `,
})
export class AbTestSectionComponent {
  readonly form = input.required<FormGroup>();
  readonly templates = input.required<Array<{ id: string; name: string }>>();
}
