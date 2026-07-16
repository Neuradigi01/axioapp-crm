import { Routes } from '@angular/router';
import { getRoute } from '@core/services/routes-helper.service';
import { AdminLayoutComponent } from './layout/admin-layout.component';

export const adminRoutes: Routes = [
  {
    path: '',
    component: AdminLayoutComponent,
    children: [
      {
        path: '',
        redirectTo: getRoute('admin_dashboard').path,
        pathMatch: 'full',
      },
      {
        path: getRoute('admin_dashboard').path,
        loadComponent: () =>
          import('./dashboard/dashboard.component').then(
            (m) => m.DashboardComponent
          ),
      },
      {
        path: getRoute('admin_profile').path,
        loadComponent: () =>
          import('./profile/profile.component').then((m) => m.ProfileComponent),
      },
      {
        path: getRoute('admin_security').path,
        loadComponent: () =>
          import('./security/security.component').then(
            (m) => m.SecurityComponent
          ),
      },
      {
        path: getRoute('admin_change_password').path,
        loadComponent: () =>
          import('./change-password/change-password.component').then(
            (m) => m.ChangePasswordComponent
          ),
      },
      {
        path: getRoute('admin_login_history').path,
        loadComponent: () =>
          import('@shared/components/login-history/login-history.component').then(
            (m) => m.LoginHistoryComponent
          ),
      },
      {
        path: getRoute('member_controls').path,
        loadChildren: () =>
          import('./member/member.routes').then((m) => m.memberRoutes),
      },
      {
        path: getRoute('sub_admin').path,
        loadChildren: () =>
          import('./sub-admin/sub-admin.routes').then((m) => m.subAdminRoutes),
      },
      {
        path: getRoute('admin_support').path,
        loadChildren: () =>
          import('./support/support.routes').then((m) => m.adminSupportRoutes),
      },
      {
        path: getRoute('admin_contact_us').path,
        loadComponent: () =>
          import('./contact-us/contact-us.component').then(
            (m) => m.ContactUsComponent
          ),
      },
      {
        path: getRoute('admin_news').path,
        loadComponent: () =>
          import('./news/news.component').then(
            (m) => m.NewsComponent
          ),
      },
      {
        path: getRoute('admin_popups').path,
        loadComponent: () =>
          import('./popups/popups.component').then(
            (m) => m.PopupsComponent
          ),
      },
      {
        path: getRoute('admin_newsletter').path,
        loadComponent: () =>
          import('./newsletter/newsletter.component').then(
            (m) => m.NewsletterComponent
          ),
      },
      {
        path: getRoute('admin_setup').path,
        loadChildren: () =>
          import('./setup/setup.routes').then((m) => m.setupRoutes),
      },
    ],
  },
];
