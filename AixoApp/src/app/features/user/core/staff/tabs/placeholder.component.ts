import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

/**
 * Generic "this tab is wired in a future phase" panel. The three
 * stubbed tabs (Field Ops / Stock Updates / Store Marketing) reuse
 * this with different copy rather than getting three near-identical
 * components.
 */
@Component({
  selector: 'app-staff-placeholder-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  template: `
    <div
      class="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-subtle bg-surface px-6 py-12 text-center"
    >
      <lucide-icon name="package" class="h-8 w-8 text-faint"></lucide-icon>
      <h3 class="text-lg font-semibold text-default">{{ title() }}</h3>
      <p class="max-w-md text-sm text-muted">{{ message() }}</p>
    </div>
  `,
})
export class StaffPlaceholderTabComponent {
  readonly title = input.required<string>();
  readonly message = input.required<string>();
}
