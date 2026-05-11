import { Component, ChangeDetectionStrategy, input, inject, effect, signal } from '@angular/core';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { UtilsApiService } from '@app/services/utils-api.service';

@Component({
  selector: 'app-show-qr',
  templateUrl: './show-qr.component.html',
  styleUrl: './show-qr.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatProgressSpinnerModule],
})
export class ShowQrComponent {
  private readonly utilsApi = inject(UtilsApiService);

  readonly data = input.required<string>();
  readonly size = input<number>(200);

  readonly qrImage = signal<string>('');
  readonly isLoading = signal<boolean>(false);

  constructor() {
    effect(() => {
      const text = this.data();
      const size = this.size();
      if (text) {
        this.loadQr(text, size);
      } else {
        this.qrImage.set('');
      }
    });
  }

  private async loadQr(text: string, size: number): Promise<void> {
    this.isLoading.set(true);
    try {
      const res = await this.utilsApi.getQR(text, size);
      if (res.success) {
        this.qrImage.set(res.data.qr_image);
      }
    } finally {
      this.isLoading.set(false);
    }
  }
}
