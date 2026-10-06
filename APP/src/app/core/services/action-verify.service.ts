import { Injectable, Injector, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { TwoFactorApiService } from '@app/services/two-factor-api.service';
import { TwoFactorMethod, IActionVerifyDialogData } from '@app/schemas/common';

@Injectable({ providedIn: 'root' })
export class ActionVerifyService {
  private readonly injector = inject(Injector);
  private readonly tfaApi = inject(TwoFactorApiService);

  async getActionToken(): Promise<string | null> {
    const statusRes = await this.tfaApi.getStatus();
    if (!statusRes.success || !statusRes.data) return null;

    const status = statusRes.data;
    const availableMethods: TwoFactorMethod[] = [];
    if (status.email_enabled && status.masked_email) availableMethods.push('email');
    if (status.sms_enabled && status.masked_mobile) availableMethods.push('sms');
    availableMethods.push('authenticator');

    // Ensure current method is first in the list
    const currentMethod = status.two_factor_method as TwoFactorMethod;
    const idx = availableMethods.indexOf(currentMethod);
    if (idx > 0) {
      availableMethods.splice(idx, 1);
      availableMethods.unshift(currentMethod);
    }

    const dialogData: IActionVerifyDialogData = {
      twoFactorMethod: status.two_factor_method as TwoFactorMethod,
      maskedEmail: status.masked_email,
      maskedMobile: status.masked_mobile,
      availableMethods,
    };

    // Loaded on demand: this service is injected by the eager auth
    // interceptor, so static imports would put MatDialog and the dialog
    // component in the initial bundle for a rarely-shown prompt.
    const [{ MatDialog }, { ActionVerifyDialogComponent }] = await Promise.all([
      import('@angular/material/dialog'),
      import('@shared/components/action-verify-dialog/action-verify-dialog.component'),
    ]);

    const dialogRef = this.injector.get(MatDialog).open(ActionVerifyDialogComponent, {
      width: '420px',
      disableClose: true,
      data: dialogData,
    });

    return firstValueFrom(dialogRef.afterClosed());
  }
}
