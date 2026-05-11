import { Component, ChangeDetectionStrategy, input, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-form-card',
  templateUrl: './form-card.component.html',
  styleUrl: './form-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatButtonModule, MatIconModule],
})
export class FormCardComponent {
  readonly title = input<string>('');
  readonly subtitle = input<string>('');
  readonly icon = input<string>('');
  readonly showBackButton = input<boolean>(false);
  readonly backClicked = output<void>();

  onBackClick(): void {
    this.backClicked.emit();
  }
}
