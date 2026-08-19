/**
 * Route tree for the AI Assistants module
 * (``tasks/ai-assistants`` Step 7).
 *
 * Two routes:
 *
 *   * ``/user/ai-assistants``       — list page (Owner + Admin + Employee
 *                                     see it read-only via ``ai_assistants.view``).
 *   * ``/user/ai-assistants/:id``   — editor page (write actions inside
 *                                     the editor are gated at the API by
 *                                     ``ai_assistants.manage``; the route
 *                                     itself is view-gated so the read-only
 *                                     view of the config is visible to
 *                                     Employees).
 *
 * Wired into ``user.routes.ts`` via ``loadChildren``.
 */
import { Routes } from '@angular/router';

import { permissionGuard } from '../auth/permission.guard';

export const AI_ASSISTANTS_ROUTES: Routes = [
  {
    path: '',
    canActivate: [permissionGuard('ai_assistants.view')],
    loadComponent: () => import('./ai-assistants.page').then((m) => m.AiAssistantsPage),
  },
  {
    path: ':id',
    canActivate: [permissionGuard('ai_assistants.view')],
    loadComponent: () =>
      import('./editor/ai-assistant-editor.page').then((m) => m.AiAssistantEditorPage),
  },
];

export default AI_ASSISTANTS_ROUTES;
