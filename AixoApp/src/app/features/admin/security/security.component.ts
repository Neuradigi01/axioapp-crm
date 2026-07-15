import { Component, ChangeDetectionStrategy } from '@angular/core';
import { TfaSettingsComponent } from '@shared/components/tfa-settings/tfa-settings.component';
import { LoginHistoryTableComponent } from '@shared/components/login-history-table/login-history-table.component';

@Component({
  selector: 'app-admin-security',
  templateUrl: './security.component.html',
  styleUrl: './security.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TfaSettingsComponent, LoginHistoryTableComponent],
})
export class SecurityComponent {}
