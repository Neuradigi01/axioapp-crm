import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { IRoute, INavMenuItem } from '@app/schemas/route';
import { AppSettings } from '@app/app.settings';

/**
 * Module-level cache populated by RoutesHelperService.loadRoutes().
 * Accessed by the standalone getRoute() function so route files and components
 * can access route metadata without dependency injection.
 */
let _routesMap: Record<string, IRoute> = {};

/**
 * Returns the full IRoute object for a given control_id.
 *
 * Usage:
 * - Route files:  `path: getRoute('login').path`
 * - Navigation:   `this.router.navigate([getRoute('user_dashboard').url])`
 * - Templates:    `[routerLink]="getRoute('register').url"`
 * - Display:      `getRoute('user_dashboard').name` → "Dashboard"
 *
 * Routes MUST be loaded from the API on app initialization.
 * Throws if the route is not found — this indicates a missing route
 * in the database or a failure to load routes from the API.
 */
export function getRoute(controlId: string): IRoute {
  const route = _routesMap[controlId];
  if (!route) {
    throw new Error(
      `Route "${controlId}" not found. Ensure routes are loaded from API before use.`,
    );
  }
  return route;
}

@Injectable({ providedIn: 'root' })
export class RoutesHelperService {
  private readonly http = inject(HttpClient);
  private routesMap: Record<string, IRoute> = {};
  private loaded = false;

  async loadRoutes(): Promise<void> {
    if (this.loaded) return;
    try {
      const response = await firstValueFrom(
        this.http.get<{ success: boolean; data: Record<string, IRoute> }>(
          `${AppSettings.ApiBaseUrl}/routes/config`,
        ),
      );
      if (response?.success && response.data) {
        this.routesMap = response.data;
        _routesMap = response.data;
        this.loaded = true;
      }
    } catch {
      this.loaded = false;
    }
  }

  getAllRoutes(): Record<string, IRoute> {
    return this.routesMap;
  }

  hasRightsToAccessUrl(url: string, accessRights: number[]): boolean {
    // Strip query params and fragment
    const cleanUrl = url.split('?')[0].split('#')[0];

    // Try exact match first
    let route = Object.values(this.routesMap).find((r) => r.url === cleanUrl);

    // If no exact match, find the longest matching route URL prefix
    // This handles parameterized routes like /admin/sub-admins/edit/:id
    if (!route) {
      let bestMatch: IRoute | undefined;
      let bestLength = 0;
      for (const r of Object.values(this.routesMap)) {
        if (cleanUrl.startsWith(r.url + '/') && r.url.length > bestLength) {
          bestMatch = r;
          bestLength = r.url.length;
        }
      }
      route = bestMatch;
    }

    if (!route) return false;

    // Routes with user_type 'Any' are accessible to everyone
    if (route.user_type === 'Any') return true;

    return accessRights.includes(route.id);
  }

  getSideNavMenusFromAccessRights(userType: string, accessRights: number[]): INavMenuItem[] {
    const accessibleRoutes = Object.values(this.routesMap).filter(
      (r) =>
        r.is_nav_menu_item &&
        accessRights.includes(r.id) &&
        (r.user_type === userType || r.user_type === 'Any'),
    );

    const topLevel = accessibleRoutes
      .filter((r) => r.nav_parent_id === 0)
      .sort((a, b) => a.order_no - b.order_no);

    return topLevel.map((route) => ({
      route,
      children: accessibleRoutes
        .filter((r) => r.nav_parent_id === route.id)
        .sort((a, b) => a.order_no - b.order_no)
        .map((child) => ({ route: child, children: [] })),
    }));
  }
}
