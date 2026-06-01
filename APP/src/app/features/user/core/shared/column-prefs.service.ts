import { Injectable } from '@angular/core';

/** Per-page column descriptor. Array order IS the column order — there's
 * no separate `order` field on purpose. */
export interface ColumnDef {
  /** Stable key — matches the corresponding `Lead` / `Contact` field
   * name so the template can look up the cell value without a lookup
   * table. */
  key: string;
  /** Header label shown in the table and in the column-customization
   * menu. */
  label: string;
  /** Whether the column is rendered. */
  visible: boolean;
}

/**
 * LocalStorage-backed column-visibility + order store. Per-page (so the
 * leads page and the contacts page don't fight over the same key) and
 * per-browser (no backend persistence yet — Step 7 migrates this to
 * `user_preferences` when saved views need to ride along).
 *
 * Robust to schema drift: if a page's defaults add a new column, it's
 * appended to the stored layout invisibly until the user opts in;
 * removed columns are silently dropped on read. That way a deploy
 * never lands a user on an empty table.
 */
@Injectable({ providedIn: 'root' })
export class ColumnPrefsService {
  private readonly KEY_PREFIX = 'crm.columns.';

  /** Read the saved layout for `page`, merged against `defaults`.
   *
   * - Order: as stored, then any new defaults appended.
   * - Visibility: as stored, defaulting to the default-visibility for
   *   unseen columns.
   * - Labels: always taken from `defaults` so a label change in code
   *   wins over a stale localStorage entry.
   */
  get(page: string, defaults: ColumnDef[]): ColumnDef[] {
    const stored = this.readRaw(page);
    if (!stored) return defaults.map((d) => ({ ...d }));

    const defaultByKey = new Map(defaults.map((d) => [d.key, d]));
    const seen = new Set<string>();
    const merged: ColumnDef[] = [];
    for (const entry of stored) {
      const def = defaultByKey.get(entry.key);
      if (!def) continue;
      merged.push({
        key: def.key,
        label: def.label,
        visible: typeof entry.visible === 'boolean' ? entry.visible : def.visible,
      });
      seen.add(entry.key);
    }
    for (const def of defaults) {
      if (!seen.has(def.key)) merged.push({ ...def });
    }
    return merged;
  }

  /** Persist the current layout. Caller is responsible for passing the
   * full ordered list — partial updates aren't supported on purpose
   * (less surface area, no merge ambiguity). */
  set(page: string, cols: ColumnDef[]): void {
    try {
      const payload = cols.map((c) => ({ key: c.key, visible: c.visible }));
      localStorage.setItem(this.storageKey(page), JSON.stringify(payload));
    } catch {
      // Storage quota / private mode / SSR — silently swallow. The UI
      // already has the in-memory state; the user just loses the
      // preference across sessions. Throwing here would crash the
      // page and the page is more important than the preference.
    }
  }

  /** Drop the stored layout for `page` so the next `get` returns the
   * defaults as-is. */
  reset(page: string): void {
    try {
      localStorage.removeItem(this.storageKey(page));
    } catch {
      // see set()
    }
  }

  private storageKey(page: string): string {
    return `${this.KEY_PREFIX}${page}`;
  }

  private readRaw(page: string): { key: string; visible: boolean }[] | null {
    try {
      const raw = localStorage.getItem(this.storageKey(page));
      if (!raw) return null;
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) return null;
      // Accept both the new shape and a future-proof drop of `label`
      // entries; reject anything malformed so we fall back to defaults.
      return parsed
        .filter(
          (e): e is { key: string; visible: boolean } =>
            !!e &&
            typeof e === 'object' &&
            typeof (e as { key: unknown }).key === 'string',
        )
        .map((e) => ({
          key: e.key,
          visible: typeof e.visible === 'boolean' ? e.visible : true,
        }));
    } catch {
      return null;
    }
  }
}
