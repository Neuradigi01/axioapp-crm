import { Routes } from '@angular/router';
import { getRoute } from '@core/services/routes-helper.service';

export const memberRoutes: Routes = [
  {
    path: '',
    redirectTo: getRoute('member_controls_member_search').path,
    pathMatch: 'full',
  },
  {
    path: getRoute('member_controls_member_search').path,
    loadComponent: () =>
      import('./member-search/member-search.component').then(
        (m) => m.MemberSearchComponent
      ),
  },
  {
    path: getRoute('member_controls_member_profile').path + '/:id',
    loadComponent: () =>
      import('./member-profile/member-profile.component').then(
        (m) => m.MemberProfileComponent
      ),
  },
];
