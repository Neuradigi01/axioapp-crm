import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  OnInit,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { Router } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { ModuleApiService, ModuleDescriptorOut } from '../../services/module-api.service';

/**
 * Global Cmd+K / Ctrl+K command palette. Rendered once by the app shell;
 * a document-level keydown listener toggles it. The result list is
 * sourced from the sidebar registry (`ModuleApiService`) so it stays in
 * sync with whatever the user is permitted to see. This is the shell
 * for the palette — future steps will fold in recent items, contacts,
 * and quick actions.
 */
@Component({
  selector: 'app-command-palette',
  standalone: true,
  imports: [LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './command-palette.component.html',
})
export class CommandPaletteComponent implements OnInit {
  private readonly moduleApi = inject(ModuleApiService);
  private readonly router = inject(Router);

  protected readonly searchInput = viewChild<ElementRef<HTMLInputElement>>('searchInput');

  protected readonly open = signal(false);
  protected readonly query = signal('');
  protected readonly highlight = signal(0);
  protected readonly modules = signal<ModuleDescriptorOut[]>([]);

  protected readonly filtered = computed<ModuleDescriptorOut[]>(() => {
    const q = this.query().trim().toLowerCase();
    const all = this.modules();
    if (q === '') return all;
    return all.filter((m) => m.name.toLowerCase().includes(q));
  });

  ngOnInit(): void {
    this.moduleApi.list().subscribe({
      next: (mods) => this.modules.set(mods),
      error: () => this.modules.set([]),
    });
  }

  @HostListener('document:keydown', ['$event'])
  onGlobalKey(e: KeyboardEvent): void {
    // Cmd+K (macOS) / Ctrl+K (Windows/Linux) toggles the palette.
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      this.toggle();
      return;
    }
    if (!this.open()) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      this.close();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      const len = this.filtered().length;
      if (len === 0) return;
      this.highlight.update((i) => (i + 1) % len);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const len = this.filtered().length;
      if (len === 0) return;
      this.highlight.update((i) => (i - 1 + len) % len);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const items = this.filtered();
      const idx = this.highlight();
      if (items.length === 0 || idx < 0 || idx >= items.length) return;
      this.navigate(items[idx]);
    }
  }

  toggle(): void {
    this.open.update((v) => !v);
    if (this.open()) {
      this.query.set('');
      this.highlight.set(0);
      // Defer focus until the input is in the DOM.
      queueMicrotask(() => this.searchInput()?.nativeElement.focus());
    }
  }

  close(): void {
    this.open.set(false);
  }

  onOverlayClick(e: MouseEvent): void {
    // Close on click of the backdrop, not the inner panel.
    if (e.target === e.currentTarget) this.close();
  }

  onQueryInput(value: string): void {
    this.query.set(value);
    this.highlight.set(0);
  }

  navigate(m: ModuleDescriptorOut): void {
    this.close();
    this.router.navigateByUrl(m.frontend_route);
  }
}
