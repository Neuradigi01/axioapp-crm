import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '@core/services/auth.service';
import { RoutesHelperService, getRoute } from '@core/services/routes-helper.service';
import { ROLE_ADMIN } from '@core/constants/app.constants';

export const authGuard: CanActivateFn = (route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const routesHelper = inject(RoutesHelperService);

  if (!auth.isLoggedIn()) {
    router.navigate([getRoute('login').url]);
    return false;
  }

  const requiredRole = route.data?.['role'] as string | undefined;
  const userDetails = auth.getUserDetails();

  if (requiredRole && userDetails?.role !== requiredRole) {
    auth.logout();
    return false;
  }

  if (userDetails && !routesHelper.hasRightsToAccessUrl(state.url, userDetails.accessRights)) {
    const dashboardUrl =
      userDetails.role === ROLE_ADMIN
        ? getRoute('admin_dashboard').url
        : getRoute('user_dashboard').url;
    router.navigate([dashboardUrl]);
    return false;
  }

  return true;
};
