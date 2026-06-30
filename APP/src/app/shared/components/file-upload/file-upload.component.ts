import { Component, ChangeDetectionStrategy, input, output, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import {
  FILE_UPLOAD_MAX_FILES,
  FILE_UPLOAD_MAX_SIZE_BYTES,
  FILE_UPLOAD_ALLOWED_EXTENSIONS,
  FILE_TYPE_ICONS,
} from '@core/constants/app.constants';
import {
  MSG_FILE_TYPE_NOT_ALLOWED,
  MSG_FILE_TOO_LARGE,
  MSG_FILE_MAX_COUNT,
} from '@core/constants/messages.constants';

@Component({
  selector: 'app-file-upload',
  templateUrl: './file-upload.component.html',
  styleUrl: './file-upload.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatButtonModule, MatIconModule],
})
export class FileUploadComponent {
  readonly maxFiles = input<number>(FILE_UPLOAD_MAX_FILES);
  readonly maxSizeBytes = input<number>(FILE_UPLOAD_MAX_SIZE_BYTES);
  readonly allowedExtensions = input<string[]>(FILE_UPLOAD_ALLOWED_EXTENSIONS);
  readonly filesChanged = output<File[]>();

  readonly selectedFiles = signal<File[]>([]);
  readonly errors = signal<string[]>([]);
  readonly isDragOver = signal(false);

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragOver.set(true);
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragOver.set(false);
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.isDragOver.set(false);
    if (event.dataTransfer?.files) {
      this.addFiles(Array.from(event.dataTransfer.files));
    }
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files) {
      this.addFiles(Array.from(input.files));
      input.value = '';
    }
  }

  removeFile(index: number): void {
    const updated = this.selectedFiles().filter((_, i) => i !== index);
    this.selectedFiles.set(updated);
    this.errors.set([]);
    this.filesChanged.emit(updated);
  }

  clearAll(): void {
    this.selectedFiles.set([]);
    this.errors.set([]);
    this.filesChanged.emit([]);
  }

  getFileIcon(file: File): string {
    const mime = file.type.toLowerCase();
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

  private addFiles(newFiles: File[]): void {
    const validationErrors: string[] = [];
    const current = this.selectedFiles();
    const remaining = this.maxFiles() - current.length;

    if (newFiles.length > remaining) {
      validationErrors.push(MSG_FILE_MAX_COUNT.replace('{count}', String(this.maxFiles())));
      newFiles = newFiles.slice(0, remaining);
    }

    const accepted: File[] = [];
    const allowed = this.allowedExtensions().map((ext) => ext.toLowerCase());

    for (const file of newFiles) {
      const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
      if (!allowed.includes(ext)) {
        validationErrors.push(`${MSG_FILE_TYPE_NOT_ALLOWED}: ${file.name}`);
        continue;
      }
      if (file.size > this.maxSizeBytes()) {
        validationErrors.push(
          `${MSG_FILE_TOO_LARGE.replace('{size}', this.formatFileSize(this.maxSizeBytes()))}: ${file.name}`,
        );
        continue;
      }
      accepted.push(file);
    }

    this.errors.set(validationErrors);

    if (accepted.length > 0) {
      const updated = [...current, ...accepted];
      this.selectedFiles.set(updated);
      this.filesChanged.emit(updated);
    }
  }
}
