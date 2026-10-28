import { Component, ChangeDetectionStrategy, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { FormCardComponent } from '@shared/components/form-card/form-card.component';
import { SetupApiService } from '@app/services/setup-api.service';
import { SNACKBAR_ACTION, SNACKBAR_DURATION } from '@core/constants/app.constants';
import { MSG_ERROR_GENERIC } from '@core/constants/messages.constants';

@Component({
  selector: 'app-encryption',
  templateUrl: './encryption.component.html',
  styleUrl: './encryption.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    FormCardComponent,
  ],
})
export class EncryptionComponent {
  private readonly setupApi = inject(SetupApiService);
  private readonly snackBar = inject(MatSnackBar);

  readonly inputText = signal('');
  readonly resultText = signal('');
  readonly isLoading = signal(false);

  async encrypt(): Promise<void> {
    const text = this.inputText().trim();
    if (!text) return;

    this.isLoading.set(true);
    try {
      const res = await this.setupApi.encryptText(text);
      if (res.success && res.data?.encrypted) {
        this.resultText.set(res.data.encrypted);
      } else {
        this.snackBar.open(res.message || MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  async decrypt(): Promise<void> {
    const text = this.inputText().trim();
    if (!text) return;

    this.isLoading.set(true);
    try {
      const res = await this.setupApi.decryptText(text);
      if (res.success && res.data?.decrypted) {
        this.resultText.set(res.data.decrypted);
      } else {
        this.snackBar.open(res.message || 'Decryption failed', SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  copyResult(): void {
    navigator.clipboard.writeText(this.resultText());
    this.snackBar.open('Copied to clipboard', SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
  }

  clear(): void {
    this.inputText.set('');
    this.resultText.set('');
  }
}
