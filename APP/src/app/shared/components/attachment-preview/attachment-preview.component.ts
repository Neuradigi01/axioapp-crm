import { Component, ChangeDetectionStrategy, inject } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { IAttachment } from '@app/schemas/ticket';

export interface IAttachmentPreviewData {
  url: string;
  type: 'image' | 'pdf';
  fileName: string;
  attachment: IAttachment;
}

@Component({
  selector: 'app-attachment-preview',
  templateUrl: './attachment-preview.component.html',
  styleUrl: './attachment-preview.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatIconModule, MatButtonModule],
})
export class AttachmentPreviewComponent {
  private readonly dialogRef = inject(MatDialogRef<AttachmentPreviewComponent>);
  private readonly sanitizer = inject(DomSanitizer);
  readonly data: IAttachmentPreviewData = inject(MAT_DIALOG_DATA);

  readonly safeUrl: SafeResourceUrl;

  constructor() {
    this.safeUrl = this.sanitizer.bypassSecurityTrustResourceUrl(this.data.url);
  }

  close(): void {
    this.dialogRef.close();
  }

  download(): void {
    this.dialogRef.close('download');
  }
}
