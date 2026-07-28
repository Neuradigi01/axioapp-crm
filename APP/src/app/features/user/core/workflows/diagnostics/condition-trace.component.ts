import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { DiagnosticsConditionTrace } from '../workflows-api.service';

/**
 * Step 19 — recursive renderer for the condition-AST evaluation
 * trace. Compound nodes (``all`` / ``any`` / ``not``) recurse into
 * their children; leaf nodes show the op / path / resolved value /
 * verdict in a compact row.
 */

@Component({
  selector: 'app-condition-trace',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let n = node();
    @switch (n.kind) {
      @case ('empty') {
        <div class="text-[10px] text-muted italic">empty condition (always matches)</div>
      }
      @case ('invalid') {
        <div class="text-[10px] text-rose-700">invalid: {{ n.error }}</div>
      }
      @case ('leaf') {
        <div
          class="flex items-center gap-2 text-[11px] py-1 px-2 rounded"
          [class.bg-emerald-50]="n.result"
          [class.text-emerald-900]="n.result"
          [class.bg-rose-50]="!n.result"
          [class.text-rose-900]="!n.result"
        >
          <span class="font-mono text-muted">{{ n.path }}</span>
          <span class="font-mono text-muted">{{ n.op }}</span>
          <span class="font-mono">{{ formatValue(n.value) }}</span>
          <span class="flex-1"></span>
          <span class="text-[10px] text-muted">resolved:</span>
          <span class="font-mono text-default">
            @if (n.missing) {
              <em>(missing)</em>
            } @else {
              {{ formatValue(n.resolved_value) }}
            }
          </span>
          <span class="font-bold">{{ n.result ? '✓' : '✗' }}</span>
        </div>
      }
      @case ('all') {
        <div class="border-l-2 border-subtle pl-3 my-1">
          <div class="text-[10px] uppercase tracking-wide text-muted mb-1">
            ALL of (AND) — {{ n.result ? 'pass' : 'fail' }}
          </div>
          @for (child of n.children ?? []; track $index) {
            <app-condition-trace [node]="child" />
          }
        </div>
      }
      @case ('any') {
        <div class="border-l-2 border-subtle pl-3 my-1">
          <div class="text-[10px] uppercase tracking-wide text-muted mb-1">
            ANY of (OR) — {{ n.result ? 'pass' : 'fail' }}
          </div>
          @for (child of n.children ?? []; track $index) {
            <app-condition-trace [node]="child" />
          }
        </div>
      }
      @case ('not') {
        <div class="border-l-2 border-subtle pl-3 my-1">
          <div class="text-[10px] uppercase tracking-wide text-muted mb-1">
            NOT — {{ n.result ? 'pass' : 'fail' }}
          </div>
          @for (child of n.children ?? []; track $index) {
            <app-condition-trace [node]="child" />
          }
        </div>
      }
    }
  `,
})
export class ConditionTraceComponent {
  readonly node = input.required<DiagnosticsConditionTrace>();

  formatValue(v: unknown): string {
    if (v === null || v === undefined) return '—';
    if (typeof v === 'string') return JSON.stringify(v);
    if (typeof v === 'number' || typeof v === 'boolean') return String(v);
    try {
      return JSON.stringify(v);
    } catch {
      return String(v);
    }
  }
}
