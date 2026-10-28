import {
  Component,
  ChangeDetectionStrategy,
  input,
  inject,
  signal,
  OnDestroy,
  effect,
} from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog } from '@angular/material/dialog';
import { IAttachment } from '@app/schemas/ticket';
import { AppSettings } from '@app/app.settings';
import { FILE_TYPE_ICONS } from '@core/constants/app.constants';
import { firstValueFrom } from 'rxjs';
import {
  AttachmentPreviewComponent,
  IAttachmentPreviewData,
} from '@shared/components/attachment-preview/attachment-preview.component';

@Component({
  selector: 'app-attachment-list',
  templateUrl: './attachment-list.component.html',
  styleUrl: './attachment-list.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatIconModule],
})
export class AttachmentListComponent implements OnDestroy {
  private readonly http = inject(HttpClient);
  private readonly dialog = inject(MatDialog);

  readonly attachments = input<IAttachment[]>([]);
  readonly thumbnailUrls = signal<Record<string, string>>({});

  private blobUrls: string[] = [];

  constructor() {
    effect(() => {
      const items = this.attachments();
      this.revokeAllUrls();
      for (const att of items) {
        if (this.isImage(att)) {
          this.loadThumbnail(att);
        }
      }
    });
  }

  ngOnDestroy(): void {
    this.revokeAllUrls();
  }

  isImage(attachment: IAttachment): boolean {
    return attachment.mime_type.startsWith('image/');
  }

  isPdf(attachment: IAttachment): boolean {
    return attachment.mime_type === 'application/pdf';
  }

  isPreviewable(attachment: IAttachment): boolean {
    return this.isImage(attachment) || this.isPdf(attachment);
  }

  getFileIcon(attachment: IAttachment): string {
    const mime = attachment.mime_type.toLowerCase();
    if (mime.startsWith('image/')) return FILE_TYPE_ICONS['image'];
    if (mime === 'application/pdf') return FILE_TYPE_ICONS['pdf'];
    if (mime.includes('word') || mime.includes('document')) return FILE_TYPE_ICONS['doc'];
    if (mime.includes('sheet') || mime.includes('excel') || mime.includes('csv'))
      return FILE_TYPE_ICONS['xls'];
    if (mime.includes('zip') || mime.includes('rar') || mime.includes('compressed'))
      return FILE_TYPE_ICONS['zip'];
    if (mime.startsWith('text/')) return FILE_TYPE_ICONS['text'];
    return FILE_TYPE_ICONS['default'];
  }

  formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  async onChipClick(attachment: IAttachment, event: Event): Promise<void> {
    event.preventDefault();
    if (this.isPreviewable(attachment)) {
      await this.openPreview(attachment);
    } else {
      await this.downloadFile(attachment);
    }
  }

  async openPreview(attachment: IAttachment): Promise<void> {
    try {
      const blob = await this.fetchBlob(attachment.stored_name);
      const url = URL.createObjectURL(blob);
      this.blobUrls.push(url);

      const dialogRef = this.dialog.open(AttachmentPreviewComponent, {
        data: {
          url,
          type: this.isImage(attachment) ? 'image' : 'pdf',
          fileName: attachment.file_name,
          attachment,
        } as IAttachmentPreviewData,
        width: '90vw',
        height: '90vh',
        maxWidth: '90vw',
        panelClass: 'attachment-preview-dialog',
      });

      const result = await firstValueFrom(dialogRef.afterClosed());

      // Revoke the preview blob URL
      URL.revokeObjectURL(url);
      this.blobUrls = this.blobUrls.filter((u) => u !== url);

      if (result === 'download') {
        await this.downloadFile(attachment);
      }
    } catch {
      await this.downloadFile(attachment);
    }
  }

  async downloadFile(attachment: IAttachment): Promise<void> {
    try {
      const blob = await this.fetchBlob(attachment.stored_name);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = attachment.file_name;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // Silently fail — user can retry
    }
  }

  private async loadThumbnail(attachment: IAttachment): Promise<void> {
    try {
      const blob = await this.fetchBlob(attachment.stored_name);
      const url = URL.createObjectURL(blob);
      this.blobUrls.push(url);
      this.thumbnailUrls.update((map) => ({ ...map, [attachment.stored_name]: url }));
    } catch {
      // Thumbnail load failed — will show file icon fallback
    }
  }

  private fetchBlob(storedName: string): Promise<Blob> {
    const url = `${AppSettings.ApiBaseUrl}/attachments/${storedName}`;
    return firstValueFrom(this.http.get(url, { responseType: 'blob' }));
  }

  private revokeAllUrls(): void {
    for (const url of this.blobUrls) {
      URL.revokeObjectURL(url);
    }
    this.blobUrls = [];
    this.thumbnailUrls.set({});
  }
}
