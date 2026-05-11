import { Routes } from '@angular/router';
import { getRoute } from '@core/services/routes-helper.service';

export const adminSupportRoutes: Routes = [
  {
    path: '',
    redirectTo: getRoute('admin_support_tickets').path,
    pathMatch: 'full',
  },
  {
    path: getRoute('admin_support_compose').path,
    loadComponent: () =>
      import('../../shared/support/compose/compose.component').then(
        (m) => m.ComposeComponent
      ),
  },
  {
    path: getRoute('admin_support_tickets').path,
    loadComponent: () =>
      import('../../shared/support/ticket-list/ticket-list.component').then(
        (m) => m.TicketListComponent
      ),
  },
  {
    path: getRoute('admin_support_view_ticket').path + '/:id',
    loadComponent: () =>
      import('../../shared/support/view-message/view-message.component').then(
        (m) => m.ViewMessageComponent
      ),
  },
];
