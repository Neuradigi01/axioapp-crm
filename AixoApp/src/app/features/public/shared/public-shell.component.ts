import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

/**
 * Minimal wrapper for every public route (properties + products).
 * Renders a transparent header with brand text + the routed child.
 * No sidebar, no user chrome, no dashboard links — a visitor should
 * never see the authenticated surface leak through.
 */
@Component({
  selector: 'app-public-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet],
  template: `
    <div class="min-h-screen bg-surface-2 text-default">
      <header class="border-b border-subtle bg-surface">
        <div class="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
          <span class="text-lg font-semibold tracking-tight">Storefront</span>
        </div>
      </header>
      <main class="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
        <router-outlet />
      </main>
      <footer class="mt-16 border-t border-subtle bg-surface py-6 text-center text-xs text-muted">
        Powered by CRM
      </footer>
    </div>
  `,
})
export class PublicShellComponent {}
