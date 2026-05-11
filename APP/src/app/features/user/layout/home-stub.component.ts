import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { AuthService } from '@core/services/auth.service';

@Component({
  selector: 'app-home-stub',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './home-stub.component.html',
})
export class HomeStubComponent {
  private readonly auth = inject(AuthService);
  protected readonly role = this.auth.getUserDetails()?.role ?? 'guest';
}
