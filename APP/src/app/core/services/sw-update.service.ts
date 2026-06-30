import { Injectable, inject, ApplicationRef } from '@angular/core';
import { SwUpdate } from '@angular/service-worker';
import { MatSnackBar } from '@angular/material/snack-bar';
import { first, filter } from 'rxjs';
import { MSG_APP_UPDATE_AVAILABLE } from '@core/constants/messages.constants';

@Injectable({ providedIn: 'root' })
export class SwUpdateService {
  private readonly swUpdate = inject(SwUpdate);
  private readonly snackBar = inject(MatSnackBar);
  private readonly appRef = inject(ApplicationRef);

  init(): void {
    if (!this.swUpdate.isEnabled) return;

    this.appRef.isStable.pipe(first((stable) => stable)).subscribe(() => this.checkForUpdates());

    this.swUpdate.versionUpdates
      .pipe(filter((evt) => evt.type === 'VERSION_READY'))
      .subscribe(() => this.promptUpdate());
  }

  private checkForUpdates(): void {
    this.swUpdate.checkForUpdate().catch(() => {});
  }

  private promptUpdate(): void {
    const ref = this.snackBar.open(MSG_APP_UPDATE_AVAILABLE, 'Update', { duration: 0 });
    ref.onAction().subscribe(() => {
      this.swUpdate.activateUpdate().then(() => document.location.reload());
    });
  }
}
