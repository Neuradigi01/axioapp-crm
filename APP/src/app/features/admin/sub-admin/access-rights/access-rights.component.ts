import { Component, ChangeDetectionStrategy, inject, signal, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { FormCardComponent } from '@shared/components/form-card/form-card.component';
import { AdminApiService } from '@app/services/admin-api.service';
import { getRoute } from '@core/services/routes-helper.service';
import { SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import {
  MSG_ERROR_GENERIC,
  MSG_ERROR_LOAD_FAILED,
  MSG_SUB_ADMIN_ROUTES_UPDATED,
  MSG_SUB_ADMIN_ROUTES_UPDATE_FAILED,
} from '@core/constants/messages.constants';
import { IAssignableRoute, IRouteTreeNode, ISubAdminDetail } from '@app/schemas/admin';

@Component({
  selector: 'app-admin-access-rights',
  templateUrl: './access-rights.component.html',
  styleUrl: './access-rights.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    MatButtonModule,
    MatIconModule,
    MatCheckboxModule,
    MatProgressSpinnerModule,
    FormCardComponent,
  ],
})
export class AccessRightsComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly adminApi = inject(AdminApiService);
  private readonly snackBar = inject(MatSnackBar);

  readonly routeTree = signal<IRouteTreeNode[]>([]);
  readonly adminDetail = signal<ISubAdminDetail | null>(null);
  readonly isLoading = signal(false);
  readonly isSaving = signal(false);

  private adminId = '';

  ngOnInit(): void {
    this.adminId = this.route.snapshot.params['id'];
    this.loadData();
  }

  async loadData(): Promise<void> {
    this.isLoading.set(true);
    try {
      const [detailRes, routesRes] = await Promise.all([
        this.adminApi.getSubAdminDetail(this.adminId),
        this.adminApi.getAssignableRoutes(),
      ]);

      if (detailRes.success && routesRes.success) {
        this.adminDetail.set(detailRes.data);
        this.routeTree.set(this.buildTree(routesRes.data, detailRes.data.route_ids));
      } else {
        this.snackBar.open(MSG_ERROR_LOAD_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  private buildTree(routes: IAssignableRoute[], assignedIds: number[]): IRouteTreeNode[] {
    const parentRoutes = routes.filter((r) => r.nav_parent_id === 0);
    return parentRoutes.map((parent) => {
      const children = routes
        .filter((r) => r.nav_parent_id === parent.id)
        .map((child) => ({
          route: child,
          children: [],
          checked: child.is_compulsory || assignedIds.includes(child.id),
          indeterminate: false,
        }));
      const allChecked = children.length > 0 && children.every((c) => c.checked);
      const someChecked = children.some((c) => c.checked);
      const parentAssigned = assignedIds.includes(parent.id);
      return {
        route: parent,
        children,
        checked: parent.is_compulsory || parentAssigned || allChecked,
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

  async onSave(): Promise<void> {
    this.isSaving.set(true);
    try {
      const res = await this.adminApi.updateSubAdminRoutes({
        admin_id: this.adminId,
        route_ids: this.getSelectedRouteIds(),
      });

      if (res.success) {
        this.snackBar.open(MSG_SUB_ADMIN_ROUTES_UPDATED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        this.router.navigate([getRoute('sub_admin').url]);
      } else {
        this.snackBar.open(res.message || MSG_SUB_ADMIN_ROUTES_UPDATE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
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
