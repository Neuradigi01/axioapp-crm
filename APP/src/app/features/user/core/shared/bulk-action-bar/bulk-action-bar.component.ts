import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { FurnitureAuthService } from '../../auth/auth.service';

/**
 * One row in the floating bulk-action toolbar.
 *
 * `permissionKey` filters the action against the signed-in user's
 * permissions — actions the user can't perform are hidden, not
 * disabled, to avoid confusion. Pass `undefined` for actions
 * everyone with list access can take (e.g. "Clear selection").
 *
 * `danger` styles the button red — used for destructive actions
 * like Delete.
 */
export interface BulkAction {
  key: string;
  label: string;
  icon: string;
  danger?: boolean;
  permissionKey?: string;
}

/**
 * Floating bar at the bottom of a list page, visible whenever the user
 * has rows selected. Shared across contacts, leads, walk-ins,
 * appointments, and tasks list pages — every list that supports
 * multi-select uses the same primitive.
 *
 * The parent component owns the selection set (a `Signal<Set<string>>`)
 * and passes its size in via `selectedCount`. Action buttons emit the
 * action `key` via `(action)`; the parent looks up the matching
 * handler (open a reassign modal, open a confirm dialog, etc.) and
 * clears selection after.
 */
@Component({
  selector: 'app-bulk-action-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './bulk-action-bar.component.html',
})
export class BulkActionBarComponent {
  private readonly auth = inject(FurnitureAuthService);

  protected readonly _selectedCount = signal(0);
  protected readonly _actions = signal<BulkAction[]>([]);

  @Input() set selectedCount(n: number) {
    this._selectedCount.set(n);
  }

  @Input() set actions(value: BulkAction[]) {
    this._actions.set(value);
  }

  @Output() readonly action = new EventEmitter<string>();
  @Output() readonly clear = new EventEmitter<void>();

  /** Hide-don't-disable: an action whose permissionKey is missing
   * from the current user's `currentPermissions` signal is filtered out. */
  protected readonly visibleActions = computed<BulkAction[]>(() => {
    const acts = this._actions();
    return acts.filter(
      (a) => !a.permissionKey || this.auth.hasPermission(a.permissionKey),
    );
  });

  protected readonly visible = computed(() => this._selectedCount() > 0);
}
