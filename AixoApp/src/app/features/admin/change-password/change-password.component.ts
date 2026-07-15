import { Component, ChangeDetectionStrategy } from '@angular/core';
import { ChangePasswordFormComponent } from '@shared/components/change-password-form/change-password-form.component';

@Component({
  selector: 'app-admin-change-password',
  templateUrl: './change-password.component.html',
  styleUrl: './change-password.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ChangePasswordFormComponent],
})
export class ChangePasswordComponent {}
