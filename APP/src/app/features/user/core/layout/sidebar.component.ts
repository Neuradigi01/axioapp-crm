import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { FurnitureAuthService } from '../auth/auth.service';
import { ModuleApiService, ModuleDescriptorOut } from '../services/module-api.service';

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './sidebar.component.html',
})
export class SidebarComponent implements OnInit {
  private readonly moduleApi = inject(ModuleApiService);
  private readonly auth = inject(FurnitureAuthService);

  /** Desktop expand/collapse state. */
  readonly expanded = input.required<boolean>();
  /** Mobile off-canvas drawer open state. */
  readonly mobileOpen = input.required<boolean>();
  /** Desktop collapse/expand toggle (chevron button). */
  readonly toggle = output<void>();
  /** Mobile drawer close (X button or nav-link tap). */
  readonly close = output<void>();

  /** Current tenant — drives the sidebar header brand. `null` until
   * the first `/me` response lands. */
  protected readonly org = this.auth.currentOrg;

  protected readonly modules = signal<ModuleDescriptorOut[]>([]);
  protected readonly error = signal<string | null>(null);

  ngOnInit(): void {
    this.moduleApi.list().subscribe({
      next: (mods) => this.modules.set(mods),
      error: () => this.error.set('Could not load modules.'),
    });
  }
}
