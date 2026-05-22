import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
} from '@angular/core';
import { Router } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { FurnitureAuthService } from '../../auth/auth.service';

/**
 * Global floating "+" button rendered once by the user shell.
 *
 * Clicking navigates to `/user/leads?new=1`; the leads page reads that
 * query param on init and opens the create-lead modal. Routing rather
 * than embedding the modal here keeps the FAB tiny and avoids
 * duplicating the lead form's standard-fields / dynamic-form deps in
 * the shell. The badge of the modal already lives next to the data it
 * needs (contacts, pipeline, custom-fields) inside the leads page.
 *
 * Permission-gated by `leads.write` (the backend's write key for
 * `POST /api/v1/leads`). When the user lacks the permission, the FAB
 * is not rendered at all.
 */
@Component({
  selector: 'app-quick-add-fab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './quick-add-fab.component.html',
})
export class QuickAddFabComponent {
  private readonly auth = inject(FurnitureAuthService);
  private readonly router = inject(Router);

  protected readonly canCreate = computed(() =>
    this.auth.currentPermissions().includes('leads.write'),
  );

  protected onClick(): void {
    this.router.navigate(['/user/leads'], { queryParams: { new: 1 } });
  }
}
