import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  HostListener,
  Input,
  OnInit,
  Output,
  ViewChild,
  computed,
  forwardRef,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import {
  BotVariable,
  BotVariableGroup,
  VariablePickerApiService,
} from './variable-picker-api.service';

/**
 * Shared variable picker for the chatbot builder.
 *
 * Two modes, one dropdown UI:
 *
 *  - `mode="field"` — full-width text input backed by a
 *    ControlValueAccessor so it plugs into `[(ngModel)]` /
 *    `[formControl]`. Used by "Save answer to" and any node config
 *    field whose value is a single variable path
 *    (e.g. `contact.first_name`). Free typing IS allowed so operators
 *    can hand-write paths the picker doesn't list; picker just makes
 *    the common paths one-click.
 *
 *  - `mode="token"` — renders as a small `{+}` icon-button that opens
 *    the same dropdown. Selecting a variable emits `(insert)` with
 *    the `{{path}}` string. Callers wire this up to insert into a
 *    linked textarea at the current cursor position — see the
 *    node-config-form's textarea integration in Step 3d.
 *
 * The dropdown is grouped (Contact / Contact — Custom / Lead / Runtime
 * / Session) with a search box at the top. `[sessionVariables]` lets
 * the caller inject the per-graph session vars (computed from the
 * bot's Ask-* nodes) alongside the API-provided groups.
 */
@Component({
  selector: 'crm-variable-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  providers: [
    {
      provide: NG_VALUE_ACCESSOR,
      useExisting: forwardRef(() => VariablePickerComponent),
      multi: true,
    },
  ],
  template: `
    <div class="relative inline-block w-full" (click)="$event.stopPropagation()">
      @if (mode === 'field') {
        <div class="flex items-center gap-1">
          <input
            #inputEl
            type="text"
            [ngModel]="value()"
            (ngModelChange)="onValueChange($event)"
            [placeholder]="placeholder"
            [disabled]="disabledState()"
            class="flex-1 min-w-0 px-3 py-2 text-xs bg-app text-default border border-subtle rounded-md placeholder:text-muted focus:outline-none focus:border-accent"
            (focus)="onFocus()"
          />
          <button
            type="button"
            (click)="toggleOpen()"
            [disabled]="disabledState()"
            class="flex-shrink-0 inline-flex items-center justify-center w-8 h-8 rounded-md border border-subtle bg-surface hover:bg-surface-2 text-muted hover:text-default disabled:opacity-50"
            [attr.aria-expanded]="open()"
            aria-label="Pick a variable"
            title="Pick a variable"
          >
            <lucide-icon name="braces" size="14"></lucide-icon>
          </button>
        </div>
      } @else {
        <button
          type="button"
          (click)="toggleOpen()"
          class="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-subtle bg-surface hover:bg-surface-2 text-[11px] font-medium text-muted hover:text-default"
          [attr.aria-expanded]="open()"
          aria-label="Insert a variable"
          title="Insert a variable"
        >
          <lucide-icon name="braces" size="12"></lucide-icon>
          <span>Variable</span>
        </button>
      }

      @if (open()) {
        <div
          class="absolute right-0 top-full mt-1 z-50 w-72 max-h-80 flex flex-col rounded-lg border border-subtle bg-surface shadow-lg"
        >
          <div class="p-2 border-b border-subtle">
            <input
              type="text"
              [ngModel]="search()"
              (ngModelChange)="search.set($event)"
              placeholder="Search variables…"
              class="w-full px-2 py-1.5 text-xs bg-app text-default border border-subtle rounded placeholder:text-muted focus:outline-none focus:border-accent"
              (click)="$event.stopPropagation()"
            />
          </div>
          <div class="flex-1 overflow-y-auto">
            @if (loading()) {
              <div class="px-3 py-4 text-[11px] text-muted text-center">Loading…</div>
            } @else if (filteredGroups().length === 0) {
              <div class="px-3 py-4 text-[11px] text-muted text-center">No matches.</div>
            } @else {
              @for (group of filteredGroups(); track group.key) {
                <div class="px-3 pt-2 pb-1 text-[10px] uppercase tracking-wider text-muted">
                  {{ group.label }}
                </div>
                @for (v of group.variables; track v.path) {
                  <button
                    type="button"
                    (click)="pickVariable(v)"
                    class="w-full text-left px-3 py-1.5 hover:bg-surface-2 focus:bg-surface-2 focus:outline-none"
                  >
                    <div class="text-xs text-default">{{ v.label }}</div>
                    <div class="text-[10px] text-muted font-mono">
                      {{ mode === 'token' ? '{{' + v.path + '}}' : v.path }}
                    </div>
                  </button>
                }
              }
            }
          </div>
        </div>
      }
    </div>
  `,
})
export class VariablePickerComponent implements ControlValueAccessor, OnInit {
  private readonly api = inject(VariablePickerApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** `"field"` — CVA-driven text input + picker. `"token"` — just the
   *  {+} icon, emits `(insert)` with the wrapped `{{path}}` string. */
  @Input() mode: 'field' | 'token' = 'field';

  /** Placeholder for the free-text input (field mode only). */
  @Input() placeholder = 'contact.first_name';

  /** Per-graph session variables from the bot's Ask-* nodes. Rendered
   *  as an extra "Session" group in the picker. */
  @Input() sessionVariables: BotVariable[] = [];

  /** Emitted by `mode="token"` when the operator picks a variable.
   *  The parent listens and inserts the token at the cursor of a
   *  linked input / textarea. Includes the leading `{{` and trailing
   *  `}}` so callers don't have to re-wrap. */
  @Output() insert = new EventEmitter<string>();

  @ViewChild('inputEl') protected inputEl?: { nativeElement: HTMLInputElement };

  protected readonly open = signal(false);
  protected readonly search = signal('');
  protected readonly loading = signal(false);
  protected readonly value = signal<string>('');
  protected readonly disabledState = signal(false);
  protected readonly apiGroups = signal<BotVariableGroup[]>([]);

  private onChange: (v: string) => void = () => undefined;
  private onTouched: () => void = () => undefined;

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

  /** Combines the API groups + the per-graph session vars (if any),
   *  filtered by the search box. Search is case-insensitive on both
   *  label and path so an operator can find `contact.first_name` by
   *  typing "first" OR "contact.first". */
  protected readonly filteredGroups = computed<BotVariableGroup[]>(() => {
    const q = this.search().trim().toLowerCase();
    const allGroups: BotVariableGroup[] = [...this.apiGroups()];
    if (this.sessionVariables.length > 0) {
      allGroups.push({
        key: 'session',
        label: 'Session (answers)',
        variables: this.sessionVariables,
      });
    }
    if (!q) return allGroups;
    return allGroups
      .map((g) => ({
        ...g,
        variables: g.variables.filter(
          (v) => v.label.toLowerCase().includes(q) || v.path.toLowerCase().includes(q),
        ),
      }))
      .filter((g) => g.variables.length > 0);
  });

  protected toggleOpen(): void {
    if (this.disabledState()) return;
    this.open.update((v) => !v);
    if (this.open()) this.search.set('');
  }

  protected onFocus(): void {
    this.onTouched();
  }

  protected onValueChange(v: string): void {
    this.value.set(v);
    this.onChange(v);
  }

  protected pickVariable(v: BotVariable): void {
    if (this.mode === 'field') {
      this.value.set(v.path);
      this.onChange(v.path);
    } else {
      this.insert.emit(`{{${v.path}}}`);
    }
    this.open.set(false);
  }

  /** Close the dropdown on outside click. Bound at host level so
   *  it fires on any click anywhere in the document. */
  @HostListener('document:click')
  protected onDocumentClick(): void {
    if (this.open()) this.open.set(false);
  }

  // --- ControlValueAccessor ------------------------------------------------
  writeValue(v: string | null | undefined): void {
    this.value.set(v ?? '');
  }
  registerOnChange(fn: (v: string) => void): void {
    this.onChange = fn;
  }
  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }
  setDisabledState(isDisabled: boolean): void {
    this.disabledState.set(isDisabled);
  }
}
