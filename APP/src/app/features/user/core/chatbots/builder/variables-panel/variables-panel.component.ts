import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  OnInit,
  Output,
  computed,
  inject,
  signal,
  input,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import {
  BotVariable,
  BotVariableGroup,
  VariablePickerApiService,
} from '../../../shared/variable-picker/variable-picker-api.service';

/**
 * Right-side collapsible Variables reference panel for the bot builder.
 *
 * Mirrors the discoverability pattern from Zapier ("Insert Data") /
 * Retool ("State" tab) / Make (draggable pill palette). The operator
 * opens the panel to browse every variable currently in scope
 * (Contact / Contact — Custom / Lead / Runtime + per-graph Session
 * answers) and clicks any row to copy the `{{path}}` token to the
 * clipboard, ready to paste into any message body or Ask-Question
 * prompt.
 *
 * Drag-and-drop insertion onto specific nodes is a follow-up: the
 * copy-to-clipboard interaction already covers the common flow
 * (browse → copy → paste) without asking the canvas to also own drop
 * targets on every text input.
 */
@Component({
  selector: 'app-variables-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  template: `
    <aside
      class="w-72 lg:w-80 flex-shrink-0 border-l border-subtle bg-surface flex flex-col h-full"
      (click)="$event.stopPropagation()"
    >
      <header class="flex items-center gap-2 px-3 py-2.5 border-b border-subtle flex-shrink-0">
        <lucide-icon name="braces" size="14" class="text-muted"></lucide-icon>
        <h2 class="flex-1 text-xs font-semibold text-default">Variables</h2>
        <button
          type="button"
          (click)="close.emit()"
          class="p-1 rounded hover:bg-surface-2 text-muted hover:text-default"
          aria-label="Close variables panel"
        >
          <lucide-icon name="x" size="14"></lucide-icon>
        </button>
      </header>

      <div class="px-3 py-2 border-b border-subtle flex-shrink-0">
        <input
          type="text"
          [ngModel]="search()"
          (ngModelChange)="search.set($event)"
          placeholder="Search variables…"
          class="w-full px-2 py-1.5 text-xs bg-app text-default border border-subtle rounded placeholder:text-muted focus:outline-none focus:border-accent"
        />
      </div>

      <div class="flex-1 overflow-y-auto">
        @if (loading()) {
          <div class="px-3 py-4 text-[11px] text-muted text-center">Loading…</div>
        } @else if (filteredGroups().length === 0) {
          <div class="px-3 py-4 text-[11px] text-muted text-center">No variables match.</div>
        } @else {
          @for (group of filteredGroups(); track group.key) {
            <div class="px-3 pt-3 pb-1 text-[10px] uppercase tracking-wider text-muted font-medium">
              {{ group.label }}
            </div>
            @for (v of group.variables; track v.path) {
              <button
                type="button"
                (click)="onCopy(v)"
                class="w-full text-left px-3 py-2 hover:bg-surface-2 focus:bg-surface-2 focus:outline-none group"
                [title]="v.description ?? ''"
              >
                <div class="flex items-center justify-between gap-2">
                  <span class="text-xs text-default truncate">{{ v.label }}</span>
                  @if (copiedPath() === v.path) {
                    <span class="text-[10px] text-emerald-500 flex-shrink-0">Copied!</span>
                  } @else {
                    <lucide-icon
                      name="copy"
                      size="11"
                      class="text-muted opacity-0 group-hover:opacity-100 flex-shrink-0"
                    ></lucide-icon>
                  }
                </div>
                <div class="text-[10px] text-muted font-mono truncate mt-0.5">
                  {{ '{{' + v.path + '}}' }}
                </div>
              </button>
            }
          }
        }
      </div>

      <footer class="px-3 py-2 border-t border-subtle flex-shrink-0">
        <p class="text-[10px] text-muted leading-relaxed">
          Click any variable to copy its <code class="text-default">{{ '{{token}}' }}</code>. Paste
          it into any message body or Ask-Question prompt.
        </p>
      </footer>
    </aside>
  `,
})
export class VariablesPanelComponent implements OnInit {
  private readonly api = inject(VariablePickerApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** Per-graph session variables (from the bot's Ask-* nodes). */
  /** Signal input so the Session group updates while the panel is open. */
  readonly sessionVariables = input<BotVariable[]>([]);

  @Output() close = new EventEmitter<void>();

  protected readonly search = signal('');
  protected readonly loading = signal(false);
  protected readonly apiGroups = signal<BotVariableGroup[]>([]);
  protected readonly copiedPath = signal<string | null>(null);

  ngOnInit(): void {
    this.loading.set(true);
    this.api
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.apiGroups.set(resp.groups ?? []);
          this.loading.set(false);
        },
        error: () => {
          this.apiGroups.set([]);
          this.loading.set(false);
        },
      });
  }

  protected readonly filteredGroups = computed<BotVariableGroup[]>(() => {
    const q = this.search().trim().toLowerCase();
    const groups: BotVariableGroup[] = [...this.apiGroups()];
    const session = this.sessionVariables();
    if (session.length > 0) {
      groups.push({
        key: 'session',
        label: 'Session (answers)',
        variables: session,
      });
    }
    if (!q) return groups;
    return groups
      .map((g) => ({
        ...g,
        variables: g.variables.filter(
          (v) => v.label.toLowerCase().includes(q) || v.path.toLowerCase().includes(q),
        ),
      }))
      .filter((g) => g.variables.length > 0);
  });

  protected onCopy(v: BotVariable): void {
    const token = `{{${v.path}}}`;
    // Best-effort clipboard write. Modern browsers require a secure
    // context (HTTPS or localhost); the fallback path uses a hidden
    // textarea + execCommand('copy') which still works in older
    // browsers and non-secure iframes.
    const writeAsync = navigator.clipboard?.writeText?.(token);
    if (writeAsync && typeof writeAsync.then === 'function') {
      writeAsync
        .then(() => this.flashCopied(v.path))
        .catch(() => this.copyViaFallback(token, v.path));
    } else {
      this.copyViaFallback(token, v.path);
    }
  }

  private copyViaFallback(text: string, path: string): void {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      this.flashCopied(path);
    } catch {
      // Give up silently — the operator can still select the mono text
      // in the row and copy manually.
    } finally {
      document.body.removeChild(ta);
    }
  }

  private flashCopied(path: string): void {
    this.copiedPath.set(path);
    setTimeout(() => {
      if (this.copiedPath() === path) this.copiedPath.set(null);
    }, 1400);
  }
}
