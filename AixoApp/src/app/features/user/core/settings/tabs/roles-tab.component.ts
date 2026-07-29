import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { FurnitureAuthService } from '../../auth/auth.service';
import { extractApiError } from '@core/services/api-error.util';

interface RoleRow {
  id: string;
  org_id: string;
  name: string;
  is_system: boolean;
  created_at: string;
  permission_count: number;
  member_count: number;
  permission_keys: string[];
}

interface PermissionRow {
  id: string;
  key: string;
  description: string | null;
  module: string;
}

interface RoleTemplate {
  key: string;
  name: string;
  description: string;
  is_system: boolean;
  is_owner: boolean;
  auto_install_on_org_create: boolean;
  permission_keys: string[];
  installed: boolean;
}

type Mode = 'list' | 'editor';

/**
 * Roles tab — list, create, edit, and delete roles in the active org.
 *
 * Two visual states inside the tab:
 *   - `list`   — table of roles (name, members, permission count, actions)
 *   - `editor` — role name input + permission-grants matrix grouped by module
 *
 * System roles (`is_system=true`) get a "View" button instead of "Edit";
 * the editor renders the matrix read-only for them. CLAUDE.md rule: core
 * + pack-installed roles stay stable; admins create custom roles instead.
 *
 * The grants matrix is rendered from `GET /permissions` (the global
 * registry — ~55 keys today, ~80 with the furniture pack) grouped by the
 * `module` column. Adding a new module just makes its keys show up in
 * the matrix; no UI change required.
 */
@Component({
  selector: 'app-settings-roles-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './roles-tab.component.html',
})
export class RolesTabComponent {
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);
  private readonly fb = inject(FormBuilder);
  private readonly base = environment.apiBaseUrl;

  protected readonly roles = signal<RoleRow[]>([]);
  protected readonly permissions = signal<PermissionRow[]>([]);
  protected readonly templates = signal<RoleTemplate[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly canWrite = signal(false);

  protected readonly mode = signal<Mode>('list');
  protected readonly editingRole = signal<RoleRow | null>(null);
  protected readonly selectedKeys = signal<Set<string>>(new Set());
  protected readonly saving = signal(false);
  protected readonly editorError = signal<string | null>(null);

  protected readonly showTemplatePicker = signal(false);
  protected readonly installingKey = signal<string | null>(null);
  protected readonly templateError = signal<string | null>(null);

  /** Templates this org hasn't instantiated yet — shown in the picker. */
  protected readonly availableTemplates = computed(() =>
    this.templates().filter((t) => !t.installed && !t.is_owner),
  );

  protected readonly nameForm = this.fb.nonNullable.group({
    name: ['', [Validators.required, Validators.maxLength(64)]],
  });

  /** Permissions grouped by module, in stable module-alphabetical order. */
  protected readonly permissionsByModule = computed(() => {
    const groups = new Map<string, PermissionRow[]>();
    for (const p of this.permissions()) {
      const arr = groups.get(p.module);
      if (arr) arr.push(p);
      else groups.set(p.module, [p]);
    }
    return Array.from(groups.entries())
      .map(([module, perms]) => ({
        module,
        perms: [...perms].sort((a, b) => a.key.localeCompare(b.key)),
      }))
      .sort((a, b) => a.module.localeCompare(b.module));
  });

  /** True iff the user is editing or viewing a system role. */
  protected readonly isReadOnly = computed(() => this.editingRole()?.is_system === true);

  constructor() {
    this.reload();
    this.auth
      .me()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (me) => this.canWrite.set(me.permission_keys.includes('roles.write')),
        error: () => this.canWrite.set(false),
      });
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    forkJoin({
      roles: this.http.get<RoleRow[]>(`${this.base}/roles`),
      permissions: this.http.get<PermissionRow[]>(`${this.base}/permissions`),
      templates: this.http.get<RoleTemplate[]>(`${this.base}/role-templates`),
    })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ roles, permissions, templates }) => {
          this.roles.set(roles);
          this.permissions.set(permissions);
          this.templates.set(templates);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.roles.set([]);
          this.permissions.set([]);
          this.templates.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load roles.');
        },
      });
  }

  protected toggleTemplatePicker(): void {
    this.templateError.set(null);
    this.showTemplatePicker.update((v) => !v);
  }

  protected installTemplate(t: RoleTemplate): void {
    if (!this.canWrite() || this.installingKey()) return;
    this.installingKey.set(t.key);
    this.templateError.set(null);
    this.http
      .post<{ id: string }>(`${this.base}/role-templates/${t.key}/install`, {})
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.installingKey.set(null);
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.installingKey.set(null);
          this.templateError.set(extractApiError(err) ?? 'Could not install template.');
        },
      });
  }

  protected isChecked(key: string): boolean {
    return this.selectedKeys().has(key);
  }

  protected toggleKey(key: string, on: boolean): void {
    if (this.isReadOnly()) return;
    this.selectedKeys.update((set) => {
      const next = new Set(set);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  protected startCreate(): void {
    this.editingRole.set(null);
    this.selectedKeys.set(new Set());
    this.nameForm.reset({ name: '' });
    this.editorError.set(null);
    this.mode.set('editor');
  }

  protected startEdit(role: RoleRow): void {
    this.editingRole.set(role);
    this.selectedKeys.set(new Set(role.permission_keys));
    this.nameForm.reset({ name: role.name });
    this.editorError.set(null);
    this.mode.set('editor');
  }

  protected cancelEditor(): void {
    this.editingRole.set(null);
    this.selectedKeys.set(new Set());
    this.editorError.set(null);
    this.mode.set('list');
  }

  protected saveEditor(): void {
    if (this.isReadOnly() || this.nameForm.invalid || this.saving()) return;
    const name = this.nameForm.getRawValue().name.trim();
    const keys = Array.from(this.selectedKeys());
    this.saving.set(true);
    this.editorError.set(null);

    const role = this.editingRole();
    const request$ = role
      ? this.http.patch<{ id: string }>(`${this.base}/roles/${role.id}`, {
          name,
          permission_keys: keys,
        })
      : this.http.post<{ id: string }>(`${this.base}/roles`, {
          name,
          permission_keys: keys,
        });

    request$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: () => {
        this.saving.set(false);
        this.mode.set('list');
        this.editingRole.set(null);
        this.reload();
      },
      error: (err: HttpErrorResponse) => {
        this.saving.set(false);
        this.editorError.set(extractApiError(err) ?? 'Could not save role.');
      },
    });
  }

  protected deleteRole(role: RoleRow): void {
    if (!this.canWrite() || role.is_system || this.saving()) return;
    if (!window.confirm(`Delete role "${role.name}"? This cannot be undone.`)) {
      return;
    }
    this.saving.set(true);
    this.editorError.set(null);
    this.http
      .delete<void>(`${this.base}/roles/${role.id}`)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.saving.set(false);
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.saving.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not delete role.');
        },
      });
  }
}
