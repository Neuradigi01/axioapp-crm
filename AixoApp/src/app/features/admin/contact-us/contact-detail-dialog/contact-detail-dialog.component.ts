import { Component, ChangeDetectionStrategy, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { IContactUs } from '@app/schemas/contact-us';
import { BADGE_MAP } from '@core/constants/app.constants';

@Component({
  selector: 'app-contact-detail-dialog',
  templateUrl: './contact-detail-dialog.component.html',
  styleUrl: './contact-detail-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DatePipe,
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
  ],
})
export class ContactDetailDialogComponent {
  readonly data: IContactUs = inject(MAT_DIALOG_DATA);
  readonly badgeMap = BADGE_MAP;

  getTypeBadge(type: string): { color: string; bgVar: string } {
    return this.badgeMap[type.toLowerCase()] ?? this.badgeMap['general'];
  }
}
