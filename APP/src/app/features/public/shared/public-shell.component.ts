import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

/**
 * Minimal wrapper for every public property route. Renders a
 * transparent header with brand text + the routed child. No
 * sidebar, no user chrome, no dashboard links — a visitor should
 * never see the authenticated surface leak through.
 */
@Component({
  selector: 'app-public-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet],
  template: `
    <div class="min-h-screen bg-zinc-50 text-zinc-900">
      <header class="border-b border-zinc-200 bg-white">
        <div class="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
          <span class="text-lg font-semibold tracking-tight">Properties</span>
        </div>
      </header>
      <main class="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
        <router-outlet />
      </main>
      <footer
        class="mt-16 border-t border-zinc-200 bg-white py-6 text-center text-xs text-zinc-500"
      >
        Powered by CRM
      </footer>
    </div>
  `,
})
export class PublicShellComponent {}
