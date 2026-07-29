import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { extractApiError } from '@core/services/api-error.util';
import { FlowPreviewComponent } from './flow-preview.component';
import { FlowCategory, FlowRow, FlowsService } from './flows.service';

interface ScreenDraft {
  id: string;
  title: string;
}

interface FieldDraft {
  type: string;
  name: string;
  label: string;
  required: boolean;
  helperText?: string;
}

interface FlowDraft {
  name: string;
  category: FlowCategory;
  screens: ScreenDraft[];
  fields: Record<string, FieldDraft[]>;
  raw: Record<string, unknown>;
}

/**
 * Step 25 — lightweight WhatsApp Flow builder.
 *
 * Per the step spec: "Templates only in v1". We don't expose
 * arbitrary JSON editing here — operators tweak labels, mark
 * required / optional, and rename screens. The category +
 * underlying field types come from the bundled template the
 * operator picked and stay fixed (that's what wires the
 * auto-action). A "Show raw JSON" toggle exposes the full Meta
 * definition for developers / Meta-changes-shipped diagnostics.
 */
@Component({
  selector: 'app-flow-builder',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, FlowPreviewComponent],
  template: `
    <div class="space-y-4">
      <header class="flex items-baseline justify-between gap-2">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">
            {{ existing() ? 'Edit flow' : 'New flow' }}
          </p>
          <p class="text-[11px] text-muted">
            Category: {{ humanCategory(draft().category) }}
            @if (existing(); as e) {
              · Status: <span class="capitalize">{{ e.status }}</span>
            }
          </p>
        </div>
        <div class="flex gap-1">
          <button
            type="button"
            (click)="cancel.emit()"
            class="rounded border border-subtle bg-surface px-3 py-1.5 text-xs text-default hover:bg-surface-2"
          >
            Cancel
          </button>
          <button
            type="button"
            [disabled]="busy() || !draft().name"
            (click)="save()"
            class="rounded bg-accent px-3 py-1.5 text-xs font-semibold text-white hover:brightness-95 disabled:opacity-50"
          >
            {{ busy() ? 'Saving…' : 'Save draft' }}
          </button>
        </div>
      </header>

      @if (error(); as err) {
        <p class="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400">
          {{ err }}
        </p>
      }
      @if (toast(); as msg) {
        <p class="rounded-md border border-subtle bg-surface-2 px-3 py-2 text-xs text-default">
          {{ msg }}
        </p>
      }

      <label class="block text-xs">
        <span class="mb-1 block font-medium text-default">Flow name</span>
        <input
          type="text"
          maxlength="128"
          class="w-full rounded-md border border-subtle px-2.5 py-1.5"
          [ngModel]="draft().name"
          (ngModelChange)="patchName($event)"
        />
      </label>

      <div class="space-y-3">
        @for (screen of draft().screens; track screen.id; let si = $index) {
          <fieldset class="rounded-md border border-subtle p-3">
            <legend class="px-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
              Screen {{ si + 1 }}
            </legend>
            <label class="mb-2 block text-xs">
              <span class="mb-1 block text-default">Title</span>
              <input
                type="text"
                class="w-full rounded-md border border-subtle px-2.5 py-1.5"
                [ngModel]="screen.title"
                (ngModelChange)="patchScreenTitle(screen.id, $event)"
              />
            </label>
            <p class="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">Fields</p>
            <div class="space-y-1.5">
              @for (field of draft().fields[screen.id] || []; track field.name) {
                <div class="grid grid-cols-12 items-center gap-2 text-xs">
                  <span class="col-span-3 truncate font-mono text-[11px] text-muted">
                    {{ field.name }}
                  </span>
                  <input
                    type="text"
                    class="col-span-6 rounded-md border border-subtle px-2 py-1"
                    [ngModel]="field.label"
                    (ngModelChange)="patchFieldLabel(screen.id, field.name, $event)"
                    [placeholder]="field.name"
                  />
                  <label class="col-span-3 flex items-center gap-1 text-[11px] text-muted">
                    <input
                      type="checkbox"
                      [checked]="field.required"
                      (change)="toggleRequired(screen.id, field.name, $any($event.target).checked)"
                    />
                    Required
                  </label>
                </div>
              }
            </div>
          </fieldset>
        }
      </div>

      <details>
        <summary
          class="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-muted hover:text-default"
        >
          Preview
        </summary>
        <div class="mt-2">
          <app-flow-preview [definition]="draft().raw" />
        </div>
      </details>

      <details>
        <summary
          class="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-muted hover:text-default"
        >
          Raw JSON (advanced)
        </summary>
        <pre
          class="mt-2 max-h-72 overflow-auto rounded-md bg-accent p-3 text-[11px] text-default"
          >{{ rawJsonText() }}</pre
        >
      </details>
    </div>
  `,
})
export class FlowBuilderComponent {
  private readonly api = inject(FlowsService);
  private readonly destroyRef = inject(DestroyRef);

  readonly existing = input<FlowRow | null>(null);
  readonly seedTemplate = input<{
    category: FlowCategory;
    definition: Record<string, unknown>;
  } | null>(null);
  readonly saved = output<FlowRow>();
  readonly cancel = output<void>();

  protected readonly draft = signal<FlowDraft>({
    name: '',
    category: 'custom',
    screens: [],
    fields: {},
    raw: {},
  });
  protected readonly busy = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly toast = signal<string | null>(null);

  protected readonly rawJsonText = computed(() => JSON.stringify(this.draft().raw, null, 2));

  constructor() {
    effect(() => {
      const ex = this.existing();
      const seed = this.seedTemplate();
      if (ex) {
        this.draft.set(this.fromRow(ex));
      } else if (seed) {
        this.draft.set(this.fromSeed(seed.category, seed.definition));
      }
    });
  }

  protected humanCategory(c: FlowCategory): string {
    switch (c) {
      case 'appointment_booking':
        return 'Appointment booking';
      case 'lead_capture':
        return 'Lead capture';
      case 'feedback':
        return 'Customer feedback';
      case 'signup':
        return 'Sign-up';
      default:
        return 'Custom';
    }
  }

  protected patchName(value: string): void {
    this.draft.update((d) => ({ ...d, name: value }));
  }

  protected patchScreenTitle(screenId: string, value: string): void {
    this.draft.update((d) => {
      const screens = d.screens.map((s) => (s.id === screenId ? { ...s, title: value } : s));
      const raw = this.rebuildRaw(d.raw, screens, d.fields);
      return { ...d, screens, raw };
    });
  }

  protected patchFieldLabel(screenId: string, fieldName: string, value: string): void {
    this.draft.update((d) => {
      const screenFields = (d.fields[screenId] || []).map((f) =>
        f.name === fieldName ? { ...f, label: value } : f,
      );
      const fields = { ...d.fields, [screenId]: screenFields };
      const raw = this.rebuildRaw(d.raw, d.screens, fields);
      return { ...d, fields, raw };
    });
  }

  protected toggleRequired(screenId: string, fieldName: string, required: boolean): void {
    this.draft.update((d) => {
      const screenFields = (d.fields[screenId] || []).map((f) =>
        f.name === fieldName ? { ...f, required } : f,
      );
      const fields = { ...d.fields, [screenId]: screenFields };
      const raw = this.rebuildRaw(d.raw, d.screens, fields);
      return { ...d, fields, raw };
    });
  }

  protected save(): void {
    const d = this.draft();
    const existing = this.existing();
    this.busy.set(true);
    this.error.set(null);
    this.toast.set(null);
    const obs = existing
      ? this.api.update(existing.id, {
          name: d.name,
          json_definition: d.raw,
        })
      : this.api.create({
          name: d.name,
          category: d.category,
          json_definition: d.raw,
        });
    obs.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (row) => {
        this.busy.set(false);
        this.toast.set('Saved.');
        this.saved.emit(row);
      },
      error: (err: HttpErrorResponse) => {
        this.busy.set(false);
        this.error.set(extractApiError(err) ?? 'Could not save flow.');
      },
    });
  }

  // --- shape helpers ---

  private fromRow(row: FlowRow): FlowDraft {
    const draft = this.fromSeed(row.category, row.json_definition);
    return { ...draft, name: row.name };
  }

  private fromSeed(category: FlowCategory, raw: Record<string, unknown>): FlowDraft {
    const screens: ScreenDraft[] = [];
    const fields: Record<string, FieldDraft[]> = {};
    const rawScreens = Array.isArray((raw as { screens?: unknown }).screens)
      ? (raw as { screens: Array<Record<string, unknown>> }).screens
      : [];
    for (const s of rawScreens) {
      const id = String(s['id'] ?? '');
      const title = String(s['title'] ?? '');
      if (!id) continue;
      screens.push({ id, title });
      const collected: FieldDraft[] = [];
      const layoutChildren =
        (s['layout'] as { children?: Array<Record<string, unknown>> })?.children ?? [];
      this.collectFields(layoutChildren, collected);
      fields[id] = collected;
    }
    return {
      name: '',
      category,
      screens,
      fields,
      raw: this.deepClone(raw),
    };
  }

  private collectFields(nodes: Array<Record<string, unknown>>, out: FieldDraft[]): void {
    for (const node of nodes) {
      const type = String(node['type'] ?? '');
      if (type === 'Form' || type === 'SingleColumnLayout') {
        const inner = node['children'];
        if (Array.isArray(inner)) {
          this.collectFields(inner as Array<Record<string, unknown>>, out);
        }
        continue;
      }
      if (type === 'Footer' || type === 'TextHeading' || type === 'TextBody') {
        continue;
      }
      const name = String(node['name'] ?? '');
      if (!name) continue;
      out.push({
        type,
        name,
        label: String(node['label'] ?? ''),
        required: node['required'] === true || node['required'] === 'true',
        helperText: node['helper-text'] ? String(node['helper-text']) : undefined,
      });
    }
  }

  private rebuildRaw(
    raw: Record<string, unknown>,
    screens: ScreenDraft[],
    fields: Record<string, FieldDraft[]>,
  ): Record<string, unknown> {
    const next = this.deepClone(raw) as {
      screens?: Array<Record<string, unknown>>;
    };
    const rawScreens = Array.isArray(next.screens) ? next.screens : [];
    for (const s of rawScreens) {
      const id = String(s['id'] ?? '');
      const matchedScreen = screens.find((x) => x.id === id);
      if (matchedScreen) {
        s['title'] = matchedScreen.title;
      }
      this.applyFieldEdits(
        (s['layout'] as { children?: Array<Record<string, unknown>> })?.children ?? [],
        fields[id] || [],
      );
    }
    return next;
  }

  private applyFieldEdits(nodes: Array<Record<string, unknown>>, edits: FieldDraft[]): void {
    for (const node of nodes) {
      const type = String(node['type'] ?? '');
      if (type === 'Form' || type === 'SingleColumnLayout') {
        const inner = node['children'];
        if (Array.isArray(inner)) {
          this.applyFieldEdits(inner as Array<Record<string, unknown>>, edits);
        }
        continue;
      }
      const name = String(node['name'] ?? '');
      const edit = edits.find((e) => e.name === name);
      if (!edit) continue;
      node['label'] = edit.label;
      node['required'] = edit.required;
    }
  }

  private deepClone<T>(v: T): T {
    return JSON.parse(JSON.stringify(v)) as T;
  }
}
