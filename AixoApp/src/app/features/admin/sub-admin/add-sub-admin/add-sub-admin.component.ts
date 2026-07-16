import { Component, ChangeDetectionStrategy, inject, signal, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { FormCardComponent } from '@shared/components/form-card/form-card.component';
import { ValidationMessageComponent } from '@shared/components/validation-message/validation-message.component';
import { PasswordToggleDirective } from '@shared/directives/password-toggle.directive';
import { matchFieldValidator } from '@shared/validators/custom-validators';
import { AdminApiService } from '@app/services/admin-api.service';
import { getRoute } from '@core/services/routes-helper.service';
import { SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import {
  MSG_ERROR_GENERIC,
  MSG_ERROR_LOAD_FAILED,
  MSG_SUB_ADMIN_CREATED,
  MSG_SUB_ADMIN_CREATE_FAILED,
} from '@core/constants/messages.constants';
import { IAssignableRoute, IRouteTreeNode } from '@app/schemas/admin';

@Component({
  selector: 'app-admin-add-sub-admin',
  templateUrl: './add-sub-admin.component.html',
  styleUrl: './add-sub-admin.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatCheckboxModule,
    MatProgressSpinnerModule,
    FormCardComponent,
    ValidationMessageComponent,
    PasswordToggleDirective,
  ],
})
export class AddSubAdminComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);
  private readonly adminApi = inject(AdminApiService);
  private readonly snackBar = inject(MatSnackBar);

  readonly adminForm: FormGroup = this.fb.group({
    admin_user_id: ['', [Validators.required, Validators.maxLength(50)]],
    password: ['', [Validators.required, Validators.minLength(8)]],
    confirm_password: ['', [Validators.required, matchFieldValidator('password')]],
    name: ['', [Validators.required, Validators.maxLength(100)]],
    email: ['', Validators.email],
    mobile_no: [''],
  });

  readonly routeTree = signal<IRouteTreeNode[]>([]);
  readonly isLoading = signal(false);
  readonly isSaving = signal(false);

  ngOnInit(): void {
    this.loadAssignableRoutes();
  }

  async loadAssignableRoutes(): Promise<void> {
    this.isLoading.set(true);
    try {
      const res = await this.adminApi.getAssignableRoutes();
      if (res.success) {
        this.routeTree.set(this.buildTree(res.data));
      } else {
        this.snackBar.open(res.message || MSG_ERROR_LOAD_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  private buildTree(routes: IAssignableRoute[]): IRouteTreeNode[] {
    const parentRoutes = routes.filter((r) => r.parent_id === 0);
    return parentRoutes.map((parent) => {
      const children = routes
        .filter((r) => r.parent_id === parent.id)
        .map((child) => ({
          route: child,
          children: [],
          checked: child.is_compulsory,
          indeterminate: false,
        }));
      const allChecked = children.length > 0 && children.every((c) => c.checked);
      const someChecked = children.some((c) => c.checked);
      return {
        route: parent,
        children,
        checked: parent.is_compulsory || allChecked,
        indeterminate: !allChecked && someChecked,
      };
    });
  }

  toggleParent(node: IRouteTreeNode): void {
    const newChecked = !node.checked;
    node.checked = newChecked;
    node.indeterminate = false;
    node.children.forEach((child) => {
      if (!child.route.is_compulsory) {
        child.checked = newChecked;
      }
    });
    this.routeTree.update((tree) => [...tree]);
  }

  toggleChild(parent: IRouteTreeNode, child: IRouteTreeNode): void {
    if (child.route.is_compulsory) return;
    child.checked = !child.checked;
    const allChecked = parent.children.every((c) => c.checked);
    const someChecked = parent.children.some((c) => c.checked);
    parent.checked = allChecked;
    parent.indeterminate = !allChecked && someChecked;
    this.routeTree.update((tree) => [...tree]);
  }

  selectAll(): void {
    this.routeTree.update((tree) =>
      tree.map((node) => ({
        ...node,
        checked: true,
        indeterminate: false,
        children: node.children.map((child) => ({ ...child, checked: true })),
      }))
    );
  }

  deselectAll(): void {
    this.routeTree.update((tree) =>
      tree.map((node) => ({
        ...node,
        checked: node.route.is_compulsory,
        indeterminate: false,
        children: node.children.map((child) => ({
          ...child,
          checked: child.route.is_compulsory,
        })),
      }))
    );
  }

  private getSelectedRouteIds(): number[] {
    const ids: number[] = [];
    for (const parent of this.routeTree()) {
      if (parent.checked || parent.indeterminate) {
        ids.push(parent.route.id);
      }
      for (const child of parent.children) {
        if (child.checked) {
          ids.push(child.route.id);
        }
      }
    }
    return ids;
  }

  async onSubmit(): Promise<void> {
    if (this.adminForm.invalid) {
      this.adminForm.markAllAsTouched();
      return;
    }

    this.isSaving.set(true);
    const val = this.adminForm.value;

    try {
      const res = await this.adminApi.createSubAdmin({
        admin_user_id: val.admin_user_id,
        password: val.password,
        name: val.name,
        email: val.email || null,
        mobile_no: val.mobile_no || null,
        route_ids: this.getSelectedRouteIds(),
      });

      if (res.success) {
        this.snackBar.open(MSG_SUB_ADMIN_CREATED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        this.router.navigate([getRoute('sub_admin').url]);
      } else {
        this.snackBar.open(res.message || MSG_SUB_ADMIN_CREATE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isSaving.set(false);
    }
  }

  goBack(): void {
    this.router.navigate([getRoute('sub_admin').url]);
  }
}
