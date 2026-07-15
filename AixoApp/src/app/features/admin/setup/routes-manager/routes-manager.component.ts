import { Component, ChangeDetectionStrategy, inject, signal, OnInit } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatDialog } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { MatTooltipModule } from '@angular/material/tooltip';
import { SetupApiService } from '@app/services/setup-api.service';
import { IRouteManagement, IRouteTreeNode } from '@app/schemas/route-management';
import { SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import {
  MSG_ERROR_GENERIC,
  MSG_ERROR_LOAD_FAILED,
  MSG_ROUTE_ACTIVE_UPDATED,
  MSG_ROUTE_ACTIVE_UPDATE_FAILED,
  MSG_ROUTE_DELETED,
  MSG_ROUTE_DELETE_FAILED,
} from '@core/constants/messages.constants';
import { RouteDialogComponent } from './route-dialog/route-dialog.component';

@Component({
  selector: 'app-routes-manager',
  templateUrl: './routes-manager.component.html',
  styleUrl: './routes-manager.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    FormsModule,
    MatButtonModule,
    MatCheckboxModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatTabsModule,
    MatTooltipModule,
  ],
})
export class RoutesManagerComponent implements OnInit {
  private readonly setupApi = inject(SetupApiService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);

  readonly isLoading = signal(false);
  readonly isSaving = signal(false);
  readonly filterText = signal('');

  private allRoutes: IRouteManagement[] = [];
  readonly adminTree = signal<IRouteTreeNode[]>([]);
  readonly userTree = signal<IRouteTreeNode[]>([]);
  readonly anyTree = signal<IRouteTreeNode[]>([]);

  readonly tabs = ['Admin', 'User', 'Any'];

  ngOnInit(): void {
    this.loadData();
  }

  async loadData(): Promise<void> {
    this.isLoading.set(true);
    try {
      const res = await this.setupApi.getAllRoutes();
      if (res.success) {
        this.allRoutes = res.data;
        this.rebuildTrees();
      } else {
        this.snackBar.open(MSG_ERROR_LOAD_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  private rebuildTrees(): void {
    const filter = this.filterText().toLowerCase();
    this.adminTree.set(this.buildTree('Admin', filter));
    this.userTree.set(this.buildTree('User', filter));
    this.anyTree.set(this.buildTree('Any', filter));
  }

  private buildTree(userType: string, filter: string): IRouteTreeNode[] {
    const routes = this.allRoutes.filter((r) => r.user_type === userType);
    const parentRoutes = routes.filter((r) => r.parent_id === 0 || !routes.some((p) => p.id === r.parent_id));
    const childMap = new Map<number, IRouteManagement[]>();

    for (const route of routes) {
      if (route.parent_id !== 0 && routes.some((p) => p.id === route.parent_id)) {
        const children = childMap.get(route.parent_id) ?? [];
        children.push(route);
        childMap.set(route.parent_id, children);
      }
    }

    const tree: IRouteTreeNode[] = parentRoutes.map((parent) => ({
      route: parent,
      children: (childMap.get(parent.id) ?? [])
        .sort((a, b) => a.order_no - b.order_no)
        .map((child) => ({
          route: child,
          children: this.buildChildrenRecursive(child.id, routes),
          expanded: true,
        })),
      expanded: true,
    }));

    if (!filter) return tree;
    return this.filterTree(tree, filter);
  }

  private buildChildrenRecursive(parentId: number, routes: IRouteManagement[]): IRouteTreeNode[] {
    const children = routes.filter((r) => r.parent_id === parentId);
    return children
      .sort((a, b) => a.order_no - b.order_no)
      .map((child) => ({
        route: child,
        children: this.buildChildrenRecursive(child.id, routes),
        expanded: true,
      }));
  }

  private filterTree(tree: IRouteTreeNode[], filter: string): IRouteTreeNode[] {
    return tree
      .map((node) => {
        const filteredChildren = this.filterTree(node.children, filter);
        const matches = node.route.name.toLowerCase().includes(filter) ||
          node.route.control_id.toLowerCase().includes(filter);
        if (matches || filteredChildren.length > 0) {
          return { ...node, children: filteredChildren, expanded: true };
        }
        return null;
      })
      .filter((n): n is IRouteTreeNode => n !== null);
  }

  onFilterChange(value: string): void {
    this.filterText.set(value);
    this.rebuildTrees();
  }

  toggleExpand(node: IRouteTreeNode): void {
    node.expanded = !node.expanded;
  }

  openAddDialog(): void {
    const dialogRef = this.dialog.open(RouteDialogComponent, {
      data: { mode: 'add' },
      width: '600px',
    });
    dialogRef.afterClosed().subscribe((result: boolean) => {
      if (result) this.loadData();
    });
  }

  openEditDialog(route: IRouteManagement): void {
    const dialogRef = this.dialog.open(RouteDialogComponent, {
      data: { mode: 'edit', route },
      width: '600px',
    });
    dialogRef.afterClosed().subscribe((result: boolean) => {
      if (result) this.loadData();
    });
  }

  async toggleActive(route: IRouteManagement): Promise<void> {
    try {
      const res = await this.setupApi.toggleActiveRoutes([route.id], !route.is_active);
      if (res.success) {
        this.snackBar.open(MSG_ROUTE_ACTIVE_UPDATED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        await this.loadData();
      } else {
        this.snackBar.open(res.message || MSG_ROUTE_ACTIVE_UPDATE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    }
  }

  async deleteRoute(route: IRouteManagement): Promise<void> {
    if (!confirm(`Delete route "${route.name}" (${route.control_id})?`)) return;

    try {
      const res = await this.setupApi.deleteRoute(route.id);
      if (res.success) {
        this.snackBar.open(MSG_ROUTE_DELETED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        await this.loadData();
      } else {
        this.snackBar.open(res.message || MSG_ROUTE_DELETE_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    }
  }

  getTreeForTab(index: number): IRouteTreeNode[] {
    switch (index) {
      case 0: return this.adminTree();
      case 1: return this.userTree();
      case 2: return this.anyTree();
      default: return [];
    }
  }
}
