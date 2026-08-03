import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  OnInit,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { Router } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { ModuleApiService, ModuleDescriptorOut } from '../services/module-api.service';

@Component({
  selector: 'app-mobile-more-sheet',
  standalone: true,
  imports: [LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './mobile-more-sheet.component.html',
})
export class MobileMoreSheetComponent implements OnInit {
  private readonly moduleApi = inject(ModuleApiService);
  private readonly router = inject(Router);

  readonly open = input.required<boolean>();
  readonly closed = output<void>();

  protected readonly modules = signal<ModuleDescriptorOut[]>([]);
  protected readonly query = signal('');
  protected readonly searchInput = viewChild<ElementRef<HTMLInputElement>>('searchInput');

  protected readonly filtered = computed<ModuleDescriptorOut[]>(() => {
    const q = this.query().trim().toLowerCase();
    const mods = this.modules();
    if (!q) return mods;
    return mods.filter((m) => m.name.toLowerCase().includes(q));
  });

  constructor() {
    // Auto-focus the search input when the sheet opens, and reset the
    // query each time it closes so re-opening starts clean.
    effect(() => {
      if (this.open()) {
        queueMicrotask(() => this.searchInput()?.nativeElement.focus());
      } else {
        this.query.set('');
      }
    });
  }

  ngOnInit(): void {
    this.moduleApi.list().subscribe({
      next: (mods) => this.modules.set(mods),
      error: () => this.modules.set([]),
    });
  }

  onQuery(value: string): void {
    this.query.set(value);
  }

  goTo(m: ModuleDescriptorOut): void {
    this.close();
    this.router.navigateByUrl(m.frontend_route);
  }

  close(): void {
    this.closed.emit();
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.open()) this.close();
  }
}
