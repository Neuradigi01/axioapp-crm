import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import {
  CONDITION_OPS,
  ConditionAnd,
  ConditionLeaf,
  ConditionNode,
  ConditionOp,
  ConditionOr,
  emptyAndGroup,
  emptyLeaf,
  VariableGroup,
} from './editors/editor-contract';

/**
 * Conditions AST builder — single recursive component.
 *
 * Renders a tree: groups (AND/OR) hold children, NOT wraps a single
 * child, leaves carry `path / op / value`. Operator-facing buttons:
 * "+ condition" adds a leaf, "+ group" adds a nested AND, the menu
 * on each group toggles AND ↔ OR / wraps in NOT / deletes.
 *
 * The path input is plain text — operators can either type a dotted
 * path or pick from the suggested groups inline. Step 15's
 * `<app-variable-picker>` is the richer browser surface; this dropdown
 * is the inline shortcut.
 */

@Component({
  selector: 'app-conditions-builder',
  standalone: true,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './conditions-builder.component.html',
})
export class ConditionsBuilderComponent {
  readonly tree = input<ConditionNode | null>(null);
  readonly variableGroups = input<readonly VariableGroup[]>([]);
  readonly treeChange = output<ConditionNode | null>();

  readonly ops = CONDITION_OPS;

  readonly suggestedPaths = computed<string[]>(() => {
    const out: string[] = [];
    for (const group of this.variableGroups()) {
      for (const p of group.paths) {
        out.push(p.path);
      }
    }
    return out;
  });

  // --- root mutations -------------------------------------------------

  addRootLeaf(): void {
    const current = this.tree();
    if (!current) {
      this.emit({ ...emptyAndGroup(), children: [emptyLeaf()] });
    } else if (current.kind === 'and' || current.kind === 'or') {
      this.emit({ ...current, children: [...current.children, emptyLeaf()] });
    } else {
      // Wrap a NOT or leaf in an AND so we can keep adding.
      this.emit({ kind: 'and', children: [current, emptyLeaf()] });
    }
  }

  clearAll(): void {
    this.emit(null);
  }

  // --- mutation helpers (immutable patch via path) --------------------

  /** Replace the subtree at `path` (array of child indices into AND/OR
   *  / NOT). `null` removes the subtree entirely. */
  replaceAt(path: number[], next: ConditionNode | null): void {
    const root = this.tree();
    if (!root) return;
    const updated = this.replaceInTree(root, path, next);
    this.emit(updated);
  }

  private replaceInTree(
    node: ConditionNode,
    path: number[],
    next: ConditionNode | null,
  ): ConditionNode | null {
    if (path.length === 0) {
      return next;
    }
    const [head, ...rest] = path;
    if (node.kind === 'and' || node.kind === 'or') {
      const newChildren = [...node.children];
      const replaced = this.replaceInTree(newChildren[head], rest, next);
      if (replaced === null) {
        newChildren.splice(head, 1);
      } else {
        newChildren[head] = replaced;
      }
      if (newChildren.length === 0) {
        return null;
      }
      return { ...node, children: newChildren };
    }
    if (node.kind === 'not') {
      const replaced = this.replaceInTree(node.child, rest, next);
      if (replaced === null) {
        return null;
      }
      return { ...node, child: replaced };
    }
    return node;
  }

  // --- child-level handlers (called from the recursive template) ------

  addChildLeaf(path: number[]): void {
    const node = this.resolve(path);
    if (!node || (node.kind !== 'and' && node.kind !== 'or')) return;
    const next: ConditionAnd | ConditionOr = {
      ...node,
      children: [...node.children, emptyLeaf()],
    };
    this.replaceAt(path, next);
  }

  addChildGroup(path: number[]): void {
    const node = this.resolve(path);
    if (!node || (node.kind !== 'and' && node.kind !== 'or')) return;
    const next: ConditionAnd | ConditionOr = {
      ...node,
      children: [...node.children, emptyAndGroup()],
    };
    this.replaceAt(path, next);
  }

  toggleAndOr(path: number[]): void {
    const node = this.resolve(path);
    if (!node || (node.kind !== 'and' && node.kind !== 'or')) return;
    const next: ConditionAnd | ConditionOr =
      node.kind === 'and'
        ? { kind: 'or', children: node.children }
        : { kind: 'and', children: node.children };
    this.replaceAt(path, next);
  }

  wrapInNot(path: number[]): void {
    const node = this.resolve(path);
    if (!node) return;
    this.replaceAt(path, { kind: 'not', child: node });
  }

  unwrapNot(path: number[]): void {
    const node = this.resolve(path);
    if (!node || node.kind !== 'not') return;
    this.replaceAt(path, node.child);
  }

  removeAt(path: number[]): void {
    this.replaceAt(path, null);
  }

  updateLeaf(path: number[], patch: Partial<Omit<ConditionLeaf, 'kind'>>): void {
    const node = this.resolve(path);
    if (!node || node.kind !== 'leaf') return;
    this.replaceAt(path, { ...node, ...patch });
  }

  onLeafPathChange(path: number[], value: string): void {
    this.updateLeaf(path, { path: value });
  }

  onLeafOpChange(path: number[], value: ConditionOp): void {
    // For `is_empty` / `is_not_empty`, clear the value field.
    const patch: Partial<Omit<ConditionLeaf, 'kind'>> = { op: value };
    if (value === 'is_empty' || value === 'is_not_empty') {
      patch.value = '';
    }
    this.updateLeaf(path, patch);
  }

  onLeafValueChange(path: number[], value: string): void {
    this.updateLeaf(path, { value });
  }

  needsValueInput(op: ConditionOp): boolean {
    return op !== 'is_empty' && op !== 'is_not_empty';
  }

  // --- private helpers ------------------------------------------------

  private resolve(path: number[]): ConditionNode | null {
    let current: ConditionNode | null = this.tree();
    for (const idx of path) {
      if (!current) return null;
      if (current.kind === 'and' || current.kind === 'or') {
        current = current.children[idx] ?? null;
      } else if (current.kind === 'not') {
        current = idx === 0 ? current.child : null;
      } else {
        return null;
      }
    }
    return current;
  }

  private emit(node: ConditionNode | null): void {
    this.treeChange.emit(node);
  }

  // --- template helpers ----------------------------------------------

  isGroup(n: ConditionNode | null): n is ConditionAnd | ConditionOr {
    return n != null && (n.kind === 'and' || n.kind === 'or');
  }

  isNot(n: ConditionNode | null): n is { kind: 'not'; child: ConditionNode } {
    return n != null && n.kind === 'not';
  }

  isLeaf(n: ConditionNode | null): n is ConditionLeaf {
    return n != null && n.kind === 'leaf';
  }

  childPath(parentPath: number[], idx: number): number[] {
    return [...parentPath, idx];
  }
}
