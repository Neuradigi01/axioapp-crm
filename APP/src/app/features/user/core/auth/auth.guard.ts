import { CanActivateFn, Router } from '@angular/router';
import { inject } from '@angular/core';

import { TokenStorageService } from './token-storage.service';

export const furnitureAuthGuard: CanActivateFn = () => {
  const storage = inject(TokenStorageService);
  const router = inject(Router);

  if (storage.getAccess()) {
    return true;
  }

  router.navigate(['/accounts/login']);
  return false;
};
