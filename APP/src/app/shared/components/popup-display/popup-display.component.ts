import { Component, ChangeDetectionStrategy, inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { AppSettings } from '@app/app.settings';

interface PopupDisplayData {
  image_path: string;
  title: string | null;
}

@Component({
  selector: 'app-popup-display',
  templateUrl: './popup-display.component.html',
  styleUrl: './popup-display.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatDialogModule, MatButtonModule, MatIconModule],
})
export class PopupDisplayComponent {
  private readonly dialogRef = inject(MatDialogRef<PopupDisplayComponent>);
  readonly data: PopupDisplayData = inject(MAT_DIALOG_DATA);

  readonly imageUrl = `${AppSettings.StaticBaseUrl}/${this.data.image_path}`;

  close(): void {
    this.dialogRef.close();
  }
}
