import { Routes } from '@angular/router';
import { getRoute } from '@core/services/routes-helper.service';
import { AccountsLayoutComponent } from './layout/accounts-layout.component';

export const accountsRoutes: Routes = [
  {
    path: '',
    component: AccountsLayoutComponent,
    children: [
      {
        path: '',
        redirectTo: getRoute('login').path,
        pathMatch: 'full',
      },
      {
        path: getRoute('login').path,
        loadComponent: () =>
          import('./login/login.component').then((m) => m.LoginComponent),
      },
      {
        path: getRoute('admin_login').path,
        loadComponent: () =>
          import('./login/login.component').then((m) => m.LoginComponent),
        data: { userType: 'Admin' },
      },
      {
        path: getRoute('register').path,
        loadComponent: () =>
          import('./register/register.component').then(
            (m) => m.RegisterComponent
          ),
      },
      {
        path: getRoute('forgot_password').path,
        loadComponent: () =>
          import('./forgot-password/forgot-password.component').then(
            (m) => m.ForgotPasswordComponent
          ),
      },
      {
        path: getRoute('reset_password').path,
        loadComponent: () =>
          import('./reset-password/reset-password.component').then(
            (m) => m.ResetPasswordComponent
          ),
      },
      {
        path: getRoute('two_factor_authentication').path,
        loadComponent: () =>
          import('./two-factor/two-factor.component').then(
            (m) => m.TwoFactorComponent
          ),
      },
      {
        path: getRoute('verify_email').path,
        loadComponent: () =>
          import('./verify-email/verify-email.component').then(
            (m) => m.VerifyEmailComponent
          ),
      },
      {
        path: getRoute('email_verification_notice').path,
        loadComponent: () =>
          import('./email-verification-notice/email-verification-notice.component').then(
            (m) => m.EmailVerificationNoticeComponent
          ),
      },
    ],
  },
];
