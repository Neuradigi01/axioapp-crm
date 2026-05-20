import { Component, ChangeDetectionStrategy } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { environment } from '../environments/environment';
import { DemoLoginsPillComponent } from './features/dev-tools/demo-logins-pill.component';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, DemoLoginsPillComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class App {
  protected readonly showDevTools = !environment.production;
}
