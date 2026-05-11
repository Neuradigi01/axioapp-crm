import { Component, ChangeDetectionStrategy, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ThemeService } from '@core/services/theme.service';

@Component({
  selector: 'app-accounts-layout',
  templateUrl: './accounts-layout.component.html',
  styleUrl: './accounts-layout.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, MatIconModule, MatButtonModule, MatTooltipModule],
})
export class AccountsLayoutComponent {
  readonly theme = inject(ThemeService);
}
