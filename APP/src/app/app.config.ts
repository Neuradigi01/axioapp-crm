import {
  ApplicationConfig,
  ErrorHandler,
  importProvidersFrom,
  provideBrowserGlobalErrorListeners,
  provideZonelessChangeDetection,
  isDevMode,
  provideAppInitializer,
  inject,
} from '@angular/core';
import { provideRouter, Router } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { provideServiceWorker } from '@angular/service-worker';
import {
  LucideAngularModule,
  ArrowRight,
  Bell,
  Calendar,
  Check,
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  Cog,
  Footprints,
  LogOut,
  Mail,
  Menu,
  MessageCircle,
  Phone,
  Plus,
  Search,
  StickyNote,
  Target,
  User,
  UserPlus,
  Users,
} from 'lucide-angular';

import { authInterceptor } from '@core/interceptors/auth.interceptor';
import { RoutesHelperService } from '@core/services/routes-helper.service';
import { ThemeService } from '@core/services/theme.service';
import { SwUpdateService } from '@core/services/sw-update.service';
import { AppConfigApiService } from '@app/services/app-config-api.service';
import { jwtInterceptor } from './features/user/core/auth/jwt.interceptor';
import { GlobalErrorHandler } from './features/user/core/error/global-error-handler';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZonelessChangeDetection(),
    provideRouter([]),
    provideHttpClient(withInterceptors([jwtInterceptor, authInterceptor])),
    { provide: ErrorHandler, useClass: GlobalErrorHandler },
    importProvidersFrom(
      LucideAngularModule.pick({
        ArrowRight,
        Bell,
        Calendar,
        Check,
        CheckSquare,
        ChevronLeft,
        ChevronRight,
        Cog,
        Footprints,
        LogOut,
        Mail,
        Menu,
        MessageCircle,
        Phone,
        Plus,
        Search,
        StickyNote,
        Target,
        User,
        UserPlus,
        Users,
      }),
    ),
    provideAnimationsAsync(),
    provideServiceWorker('ngsw-worker.js', {
      enabled: !isDevMode(),
      registrationStrategy: 'registerWhenStable:30000',
    }),
    provideAppInitializer(async () => {
      const routesHelper = inject(RoutesHelperService);
      const router = inject(Router);
      const theme = inject(ThemeService);
      const swUpdate = inject(SwUpdateService);
      const appConfigApi = inject(AppConfigApiService);

      theme.init();
      swUpdate.init();
      await Promise.all([routesHelper.loadRoutes(), appConfigApi.load()]);

      // Dynamic import so getRoute() has data when appRoutes const evaluates
      const { appRoutes } = await import('./app.routes');
      router.resetConfig(appRoutes);
    }),
  ],
};
