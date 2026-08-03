import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { ModuleApiService, ModuleDescriptorOut } from '../services/module-api.service';
import { MobileMoreSheetComponent } from './mobile-more-sheet.component';

/** Number of modules pinned to the bottom nav; the rest live in the
 * "More" sheet. Four leaves room for the trailing More tile at
 * `min-w:346px` without crowding. */
const PINNED_COUNT = 4;

@Component({
  selector: 'app-bottom-nav',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, LucideAngularModule, MobileMoreSheetComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './bottom-nav.component.html',
})
export class BottomNavComponent implements OnInit {
  private readonly moduleApi = inject(ModuleApiService);

  protected readonly modules = signal<ModuleDescriptorOut[]>([]);
  protected readonly moreOpen = signal(false);

  /** First N modules by menu_position — pinned to the bar. */
  protected readonly pinned = computed<ModuleDescriptorOut[]>(() =>
    this.modules().slice(0, PINNED_COUNT),
  );

  openMore(): void {
    this.moreOpen.set(true);
  }

  closeMore(): void {
    this.moreOpen.set(false);
  }

  ngOnInit(): void {
    this.moduleApi.list().subscribe({
      next: (mods) => this.modules.set(mods),
      error: () => this.modules.set([]),
    });
  }
}
